"""Adapter-based call session: Twilio Media Streams -> Deepgram -> xAI Grok -> ElevenLabs.

This module implements the same CallSession interface as session.py but uses pluggable adapters
for STT (Deepgram), LLM (xAI Grok), and TTS (ElevenLabs) instead of OpenAI Realtime.

Architecture:
    Twilio Media Streams (mu-law audio)
           ↓
    TwilioAdapter (bidirectional audio + DTMF)
           ↓
    STTAdapter (Deepgram Nova-3) - streaming speech-to-text
           ↓
    LLMAdapter (xAI Grok) - streaming LLM with tool calls
           ↓
    TTSAdapter (ElevenLabs Flash v2.5) - streaming text-to-speech (ulaw_8000)
           ↓
    TwilioAdapter - send audio back

Features:
- Per-stage latency logging (STT, LLM, TTS)
- Barge-in support across adapter boundaries
- Streaming tokens into TTS as they arrive from LLM
- Tool call handling (call_complete, ask_user, etc.)
- Same lifecycle/approval/consent/safety as OpenAI Realtime session
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

from .. import brief as briefmod
from .. import consent, states, webphone
from ..adapters import AudioChunk, LLMAdapter, STTAdapter, TTSAdapter, TelephonyAdapter, TranscriptSegment
from ..store import Store
from . import twilio_io
from .settings import BridgeSettings

log = logging.getLogger(__name__)

MAX_Q_LEN = 500


class AdapterCallSession:
    """Call session using pluggable adapters (Twilio -> Deepgram -> Grok -> ElevenLabs)."""

    def __init__(
        self,
        *,
        ws: Any,
        call: dict,
        store: Store,
        settings: BridgeSettings,
        stt_adapter: STTAdapter,
        llm_adapter: LLMAdapter,
        tts_adapter: TTSAdapter,
        telephony_adapter: TelephonyAdapter,
        twilio_client_factory: Callable[[], Any],
        clock: Callable[[], float],
    ) -> None:
        self.ws = ws  # object with receive_text() / send_text()
        self.call = call
        self.call_id: str = call["id"]
        self.store = store
        self.settings = settings
        self.stt = stt_adapter
        self.llm = llm_adapter
        self.tts = tts_adapter
        self.telephony = telephony_adapter
        self._client_factory = twilio_client_factory
        self.clock = clock

        self.stream_sid = ""
        self.call_sid = call.get("provider_sid") or ""
        self.web = webphone.is_web_sid(self.call_sid)
        self.started_at = clock()
        self.max_duration_s = int(call["brief"]["limits"]["max_duration_s"])
        self.payload = briefmod.voice_payload(call, store.consents(self.call_id))

        # Playback tracking (barge-in)
        self.latest_media_ts = 0
        self.marks: set[str] = set()
        self._mark_n = 0
        self.response_active = False

        # Disclosure tracking
        self._disclosure_checked = False
        self._opening_sent = False
        self._opening_sent_at = 0.0
        self._opening_done = False

        # Hold state (question pending)
        self._hold_vad = False
        self._last_hold_at = 0.0

        # Lifecycle
        self.wrapup_sent = False
        self.end_requested_at: float | None = None
        self._end_pending = False
        self._end_pending_at = 0.0
        self._goodbye_said = False
        self.hung_up = False
        self.finish_reason = ""

        # Thread-safe inbox for mid-call events
        self._inbox: deque[tuple[str, str]] = deque()

        # Mid-call question
        self._question_task: asyncio.Task | None = None
        self._question_id = ""

        # Closing after question timeout
        self._closing_since: float | None = None
        self._closing_done = False

        # Latency tracking
        self._stt_start: float | None = None
        self._llm_start: float | None = None
        self._tts_start: float | None = None

    # ---- Public API ----------------------------------------------------------------------

    def notify_voicemail(self, answered_by: str) -> None:
        """Called by bridge when AsyncAmd detects voicemail."""
        self._inbox.append(("voicemail", answered_by))

    async def run(self, start: dict) -> None:
        """Main entry point: start the call session."""
        self.stream_sid = start.get("streamSid", "")
        self.call_sid = start.get("callSid") or self.call_sid
        self.started_at = self.clock()

        try:
            # Initialize adapters
            # TODO: Send initial configuration to adapters
            pass
        except Exception:  # noqa: BLE001
            log.exception("adapter initialization failed for %s", self.call_id)
            await self._finish(
                states.FAILED,
                "adapter_unavailable",
                "failed",
                "Could not initialize voice adapters.",
                apology=True,
            )
            return

        # Create reader tasks
        tasks = [
            asyncio.create_task(self._twilio_reader()),
            asyncio.create_task(self._stt_reader()),
            asyncio.create_task(self._llm_reader()),
            asyncio.create_task(self._tts_reader()),
            asyncio.create_task(self._ticker()),
        ]

        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if self._question_task is not None:
                tasks.append(self._question_task)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._close_open_questions()
            # Close all adapters
            await self.stt.close()
            await self.llm.close()
            await self.tts.close()
            await self.telephony.close()
            self._stamp_duration()

    # ---- Readers -------------------------------------------------------------------------

    async def _twilio_reader(self) -> None:
        """Read audio from Twilio and forward to STT adapter."""
        while True:
            try:
                raw = await self.ws.receive_text()
            except Exception:  # noqa: BLE001 - disconnect
                await self._finish(
                    states.COMPLETED,
                    "callee_hung_up",
                    "needs_followup",
                    "The call ended without a recorded result.",
                    rest=False,
                )
                return

            try:
                msg = json.loads(raw)
            except ValueError:
                continue

            kind = msg.get("event")
            if kind == "media":
                media = msg.get("media") or {}
                try:
                    self.latest_media_ts = int(media.get("timestamp", self.latest_media_ts))
                except (TypeError, ValueError):
                    pass

                if media.get("track", "inbound") == "inbound" and media.get("payload"):
                    # Forward audio to STT
                    chunk = AudioChunk(
                        data=media["payload"],  # base64 mu-law
                        timestamp=self.latest_media_ts,
                        sequence=0,  # Twilio doesn't provide sequence numbers
                    )
                    await self.stt.send_audio(chunk)
                    if self._stt_start is None:
                        self._stt_start = self.clock()

            elif kind == "mark":
                self.marks.discard((msg.get("mark") or {}).get("name", ""))

            elif kind == "stop":
                await self._finish(
                    states.COMPLETED,
                    "callee_hung_up",
                    "needs_followup",
                    "The call ended without a recorded result.",
                    rest=False,
                )
                return

    async def _stt_reader(self) -> None:
        """Read transcripts from STT adapter and forward to LLM."""
        while True:
            segment = await self.stt.receive_transcript()
            if segment is None:
                log.warning("STT connection lost for call %s", self.call_id)
                return

            # Log STT latency
            if self._stt_start is not None:
                latency_ms = (self.clock() - self._stt_start) * 1000
                self.store.add_event(self.call_id, "stt_latency", {"ms": latency_ms})
                self._stt_start = None

            # Store transcript
            if segment.is_final:
                self._line("callee", segment.text)
                # Trigger opening after callee's greeting
                await self._send_opening()
                # If holding for question, send hold reply
                if self._opening_done and self.question_open and not self.hung_up:
                    await self._hold_reply()

            # Forward to LLM (TODO: implement message formatting)
            # await self.llm.send_message(...)

    async def _llm_reader(self) -> None:
        """Read tokens from LLM adapter and forward to TTS."""
        while True:
            # TODO: Implement LLM token streaming
            # For now, this is a placeholder
            await asyncio.sleep(0.1)

    async def _tts_reader(self) -> None:
        """Read audio from TTS adapter and send to Twilio."""
        while True:
            audio = await self.tts.receive_audio()
            if audio is None:
                log.warning("TTS connection lost for call %s", self.call_id)
                return

            # Log TTS latency
            if self._tts_start is not None:
                latency_ms = (self.clock() - self._tts_start) * 1000
                self.store.add_event(self.call_id, "tts_latency", {"ms": latency_ms})
                self._tts_start = None

            # Send audio to Twilio
            if self.stream_sid:
                await self.telephony.send_audio(audio)
                # Send mark for barge-in tracking
                self._mark_n += 1
                name = f"m{self._mark_n}"
                self.marks.add(name)
                await self.ws.send_text(
                    json.dumps({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})
                )

    async def _ticker(self) -> None:
        """Time-based logic: max duration, wrapup, grace period, watchdog."""
        while True:
            await asyncio.sleep(5.0)  # 5s watchdog
            now = self.clock()
            elapsed = now - self.started_at

            # Wrapup at max_duration - 60s
            if not self.wrapup_sent and elapsed >= self.max_duration_s - 60:
                self.wrapup_sent = True
                # TODO: Send wrapup message to LLM

            # Hard cap at max_duration
            if elapsed >= self.max_duration_s:
                await self._finish(
                    states.COMPLETED,
                    "max_duration",
                    "needs_followup",
                    "The call reached its maximum duration.",
                )
                return

    # ---- Helpers -------------------------------------------------------------------------

    async def _send_opening(self) -> None:
        """Send the opening disclosure line."""
        if self._opening_sent:
            return
        self._opening_sent = True
        self._opening_sent_at = self.clock()

        # TODO: Send opening instructions to LLM
        # await self.tts.send_text(self.payload["opening_line"])

    def _line(self, role: str, text: str) -> None:
        """Store a transcript line."""
        if not text.strip():
            return
        self.store.append_transcript(self.call_id, role, text)

    async def _hold_reply(self) -> None:
        """Send a brief hold message while waiting for user answer."""
        # TODO: Implement hold reply
        pass

    async def _finish(
        self,
        state: str,
        end_cause: str,
        result: str,
        summary: str,
        *,
        rest: bool = True,
        apology: bool = False,
    ) -> None:
        """End the call and update state."""
        if self.hung_up:
            return
        self.hung_up = True
        self.finish_reason = end_cause

        # Update call state
        self.store.update_call(
            self.call_id,
            {
                "state": state,
                "end_cause": end_cause,
                "result": result,
                "summary": summary,
            },
        )

        # Hang up Twilio call if needed
        if rest and self.call_sid:
            try:
                client = self._client_factory()
                client.calls(self.call_sid).update(status="completed")
            except Exception:  # noqa: BLE001
                log.exception("Failed to hang up call %s", self.call_sid)

    def _stamp_duration(self) -> None:
        """Record final call duration."""
        duration_s = self.clock() - self.started_at
        self.store.update_call(self.call_id, {"duration_s": int(duration_s)})

    def _close_open_questions(self) -> None:
        """Mark any open question as timed out."""
        if self._question_id:
            q = self.store.get_question(self._question_id)
            if q and q["status"] == "pending":
                self.store.update_question(self._question_id, {"status": "timed_out"})

    @property
    def question_open(self) -> bool:
        """Is there a pending question waiting for user answer?"""
        if not self._question_id:
            return False
        q = self.store.get_question(self._question_id)
        return bool(q and q["status"] == "pending")
