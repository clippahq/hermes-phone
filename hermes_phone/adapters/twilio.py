"""Twilio Media Streams telephony adapter.

Bidirectional audio over WebSocket with mu-law 8kHz encoding.
Supports DTMF sending via Twilio REST API and barge-in with clear command.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from . import AudioChunk, TelephonyAdapter


log = logging.getLogger(__name__)


class TwilioTelephonyAdapter:
    """Twilio Media Streams adapter for bidirectional telephony.
    
    Args:
        ws: WebSocket connection to Twilio
        call_sid: Twilio call SID for REST API operations
        twilio_client: Twilio REST client for DTMF and call control
    """
    
    def __init__(
        self,
        ws: Any,
        call_sid: str,
        twilio_client: Any = None,
    ) -> None:
        self.ws = ws
        self.call_sid = call_sid
        self.twilio_client = twilio_client
        self.stream_sid = ""
        self.latest_media_ts = 0
        self._recv_queue: asyncio.Queue[AudioChunk | None] = asyncio.Queue()
        self._recv_task: asyncio.Task | None = None
    
    async def connect(self) -> None:
        """Start receiving audio from Twilio."""
        self._recv_task = asyncio.create_task(self._receiver())
    
    async def _receiver(self) -> None:
        """Background task to receive audio from Twilio Media Streams."""
        try:
            while True:
                try:
                    raw = await self.ws.receive_text()
                    msg = json.loads(raw)
                    kind = msg.get("event")
                    
                    if kind == "start":
                        self.stream_sid = msg.get("start", {}).get("streamSid", "")
                        log.info("Twilio stream started: %s", self.stream_sid)
                    
                    elif kind == "media":
                        media = msg.get("media") or {}
                        try:
                            self.latest_media_ts = int(media.get("timestamp", self.latest_media_ts))
                        except (TypeError, ValueError):
                            pass
                        
                        if media.get("track", "inbound") == "inbound" and media.get("payload"):
                            chunk = AudioChunk(
                                data=media["payload"],  # Base64-encoded mu-law
                                format="audio/pcmu",
                                timestamp_ms=self.latest_media_ts,
                            )
                            await self._recv_queue.put(chunk)
                    
                    elif kind == "stop":
                        log.info("Twilio stream stopped")
                        break
                
                except Exception as e:  # noqa: BLE001
                    log.warning("Twilio receiver error: %s", e)
                    break
        finally:
            await self._recv_queue.put(None)
    
    async def send_audio(self, chunk: AudioChunk) -> None:
        """Send audio to Twilio for playback to caller."""
        if not self.stream_sid:
            return
        
        try:
            # Ensure payload is base64-encoded
            if isinstance(chunk.data, bytes):
                payload = base64.b64encode(chunk.data).decode()
            else:
                payload = chunk.data
            
            message = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": payload,
                },
            }
            await self.ws.send_text(json.dumps(message))
        except Exception as e:  # noqa: BLE001
            log.warning("Twilio send_audio error: %s", e)
    
    async def receive_audio(self) -> AudioChunk | None:
        """Receive audio from Twilio. None on disconnect."""
        return await self._recv_queue.get()
    
    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF tones for IVR navigation via Twilio REST API.
        
        Note: Twilio Media Streams doesn't support outbound DTMF over WebSocket,
        so we use the REST API to update the call with <Play digits="..."/>.
        """
        if not self.twilio_client or not self.call_sid:
            log.warning("Cannot send DTMF: no Twilio client or call SID")
            return
        
        try:
            # Update call with TwiML to play DTMF
            twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Play digits="{digits}"/></Response>'
            await asyncio.to_thread(
                lambda: self.twilio_client.calls(self.call_sid).update(twiml=twiml)
            )
        except Exception as e:  # noqa: BLE001
            log.error("Failed to send DTMF: %s", e)
    
    async def clear_audio(self) -> None:
        """Clear outbound audio queue (barge-in support)."""
        if not self.stream_sid:
            return
        
        try:
            message = {
                "event": "clear",
                "streamSid": self.stream_sid,
            }
            await self.ws.send_text(json.dumps(message))
        except Exception as e:  # noqa: BLE001
            log.warning("Twilio clear_audio error: %s", e)
    
    async def close(self) -> None:
        """Close the telephony connection."""
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        
        try:
            await self.ws.close()
        except Exception:  # noqa: BLE001
            pass
