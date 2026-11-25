"""Deepgram Nova-3 STT adapter with Arabic language support.

Supports ar-SA, ar-AE, ar, and multi-language mode with language_hint=ar,en.
Includes Bahraini lexicon keyterm prompting for local names and venues.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Mapping
from typing import Any

from . import AudioChunk, TranscriptSegment

log = logging.getLogger(__name__)

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
BAHRAINI_KEYTERMS = [
    "Al Khalifa", "Manama", "Adliya", "Seef", "Juffair", "Riffa",
    "Muharraq", "Budaiya", "Saar", "Hamad Town",
]


class DeepgramSTTAdapter:
    """Streaming speech-to-text via Deepgram Nova-3.

    Args:
        api_key: Deepgram API key
        language: Language code ("ar-SA", "ar-AE", "ar", "multi")
        model: Deepgram model (default: "nova-3")
        endpointing_ms: Silence threshold for utterance end (100-500ms)
    """

    def __init__(
        self,
        api_key: str,
        language: str = "multi",
        model: str = "nova-3",
        endpointing_ms: int = 300,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.language = language
        self.model = model
        self.endpointing_ms = endpointing_ms
        self._ws: Any = None
        self._recv_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[TranscriptSegment | None] = asyncio.Queue()

    async def connect(self) -> None:
        """Establish WebSocket connection to Deepgram."""
        from websockets.asyncio.client import connect

        params = {
            "model": self.model,
            "encoding": "mulaw",
            "sample_rate": 8000,
            "channels": 1,
            "endpointing": str(self.endpointing_ms),
            "punctuate": "true",
            "interim_results": "true",
        }

        if self.language == "multi":
            params["language"] = "multi"
            params["detect_language"] = "true"
            # Language hints for multi-language mode
            params["language_hint"] = "ar,en"
        else:
            params["language"] = self.language

        # Add Bahraini keyterm prompting if available
        if BAHRAINI_KEYTERMS:
            params["keywords"] = ",".join(BAHRAINI_KEYTERMS)

        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{DEEPGRAM_WS_URL}?{query}"

        self._ws = await connect(
            url,
            additional_headers={"Authorization": f"Token {self.api_key}"},
            max_size=None,
        )
        self._recv_task = asyncio.create_task(self._receiver())

    async def _receiver(self) -> None:
        """Background task to receive transcripts from Deepgram."""
        try:
            while self._ws:
                try:
                    raw = await self._ws.recv()
                    data = json.loads(raw) if isinstance(raw, str) else {}

                    if data.get("type") == "Results":
                        channel = data.get("channel", {})
                        alternatives = channel.get("alternatives", [])
                        if alternatives:
                            alt = alternatives[0]
                            transcript = alt.get("transcript", "").strip()
                            if transcript:
                                is_final = channel.get("is_final", False)
                                detected_lang = alt.get("language")
                                confidence = alt.get("confidence")

                                segment = TranscriptSegment(
                                    text=transcript,
                                    is_final=is_final,
                                    language=detected_lang,
                                    confidence=confidence,
                                )
                                await self._queue.put(segment)

                except Exception as e:  # noqa: BLE001
                    log.warning("Deepgram receiver error: %s", e)
                    break
        finally:
            await self._queue.put(None)

    async def send_audio(self, chunk: AudioChunk) -> None:
        """Send audio chunk to Deepgram for transcription."""
        if not self._ws:
            return

        try:
            # Deepgram expects raw mu-law bytes, decode base64 if needed
            if chunk.format == "audio/pcmu" and isinstance(chunk.data, str):
                audio_bytes = base64.b64decode(chunk.data)
            else:
                audio_bytes = chunk.data if isinstance(chunk.data, bytes) else chunk.data.encode()

            await self._ws.send(audio_bytes)
        except Exception as e:  # noqa: BLE001
            log.warning("Deepgram send_audio error: %s", e)

    async def receive_transcript(self) -> TranscriptSegment | None:
        """Receive next transcript segment. None when stream ends."""
        return await self._queue.get()

    async def close(self) -> None:
        """Close the STT connection."""
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            try:
                # Send close frame to Deepgram
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._ws = None
