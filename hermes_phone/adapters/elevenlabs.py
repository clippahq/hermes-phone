"""ElevenLabs Flash v2.5 TTS adapter with native ulaw_8000 output.

Supports Arabic with Gulf/Khaleeji voices from the Voice Library.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Mapping
from typing import Any

from . import TTSChunk

log = logging.getLogger(__name__)

ELEVENLABS_WS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"


class ElevenLabsTTSAdapter:
    """Streaming text-to-speech via ElevenLabs Flash v2.5.

    Args:
        api_key: ElevenLabs API key
        voice_id: Voice ID or name from Voice Library
        model: TTS model (default: "eleven_flash_v2_5")
        output_format: Audio format (default: "ulaw_8000" for telephony)
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model: str = "eleven_flash_v2_5",
        output_format: str = "ulaw_8000",
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.output_format = output_format
        self._ws: Any = None
        self._recv_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[TTSChunk | None] = asyncio.Queue()
        self._sequence = 0

    async def connect(self) -> None:
        """Establish WebSocket connection to ElevenLabs."""
        from websockets.asyncio.client import connect

        url = ELEVENLABS_WS_URL.format(voice_id=self.voice_id)
        query_params = f"model_id={self.model}&output_format={self.output_format}"
        full_url = f"{url}?{query_params}"

        self._ws = await connect(
            full_url,
            additional_headers={"xi-api-key": self.api_key},
            max_size=None,
        )

        # Send initial config
        config = {
            "text": " ",  # Initial space to start the stream
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
            "xi_api_key": self.api_key,
        }
        await self._ws.send(json.dumps(config))

        self._recv_task = asyncio.create_task(self._receiver())

    async def _receiver(self) -> None:
        """Background task to receive audio chunks from ElevenLabs."""
        try:
            while self._ws:
                try:
                    message = await self._ws.recv()

                    if isinstance(message, bytes):
                        # Raw audio chunk
                        chunk = TTSChunk(
                            audio=message,
                            format=self.output_format,
                            sequence=self._sequence,
                        )
                        self._sequence += 1
                        await self._queue.put(chunk)

                    elif isinstance(message, str):
                        # JSON message (status updates, errors, etc.)
                        try:
                            data = json.loads(message)
                            if data.get("audio"):
                                # Base64-encoded audio in JSON
                                audio_bytes = base64.b64decode(data["audio"])
                                chunk = TTSChunk(
                                    audio=audio_bytes,
                                    format=self.output_format,
                                    sequence=self._sequence,
                                )
                                self._sequence += 1
                                await self._queue.put(chunk)
                        except json.JSONDecodeError:
                            pass

                except Exception as e:  # noqa: BLE001
                    log.warning("ElevenLabs receiver error: %s", e)
                    break
        finally:
            await self._queue.put(None)

    async def send_text(self, text: str, voice: str | None = None) -> None:
        """Send text for synthesis."""
        if not self._ws:
            return

        try:
            message = {
                "text": text,
                "try_trigger_generation": True,
            }
            await self._ws.send(json.dumps(message))
        except Exception as e:  # noqa: BLE001
            log.warning("ElevenLabs send_text error: %s", e)

    async def receive_audio(self) -> TTSChunk | None:
        """Receive synthesized audio chunk. None when stream ends."""
        return await self._queue.get()

    async def flush(self) -> None:
        """Flush any buffered audio."""
        if not self._ws:
            return

        try:
            # Send empty string with flush flag
            message = {
                "text": "",
                "flush": True,
            }
            await self._ws.send(json.dumps(message))
        except Exception as e:  # noqa: BLE001
            log.warning("ElevenLabs flush error: %s", e)

    async def close(self) -> None:
        """Close the TTS connection."""
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._ws = None
