"""Pluggable adapters for telephony, STT, LLM, and TTS.

This module defines protocols for each stage of the voice pipeline, enabling swappable
providers while keeping the core call logic intact. Phase 1 implements Deepgram Nova-3 STT,
xAI Grok LLM, and ElevenLabs Flash v2.5 TTS over Twilio Media Streams.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, Any
from dataclasses import dataclass


@dataclass
class AudioChunk:
    """Raw audio data with format metadata."""
    data: bytes  # base64-encoded for mu-law, or raw bytes
    format: str  # "audio/pcmu" (8kHz mu-law), "ulaw_8000", etc.
    timestamp_ms: int = 0


@dataclass
class TranscriptSegment:
    """STT output segment."""
    text: str
    is_final: bool
    language: str | None = None
    confidence: float | None = None


@dataclass
class LLMMessage:
    """LLM turn message."""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass
class TTSChunk:
    """TTS output audio chunk."""
    audio: bytes  # base64 mu-law or raw bytes
    format: str
    sequence: int = 0


class TelephonyAdapter(Protocol):
    """Bidirectional telephony interface (Twilio Media Streams, Telnyx, etc.)."""
    
    async def send_audio(self, chunk: AudioChunk) -> None:
        """Send audio to the telephony provider."""
        ...
    
    async def receive_audio(self) -> AudioChunk | None:
        """Receive audio from the telephony provider. None on disconnect."""
        ...
    
    async def send_dtmf(self, digits: str) -> None:
        """Send DTMF tones for IVR navigation."""
        ...
    
    async def clear_audio(self) -> None:
        """Clear outbound audio queue (barge-in)."""
        ...
    
    async def close(self) -> None:
        """Close the telephony connection."""
        ...


class STTAdapter(Protocol):
    """Streaming speech-to-text interface."""
    
    async def send_audio(self, chunk: AudioChunk) -> None:
        """Send audio for transcription."""
        ...
    
    async def receive_transcript(self) -> TranscriptSegment | None:
        """Receive transcription segments. None on stream end."""
        ...
    
    async def close(self) -> None:
        """Close the STT connection."""
        ...


class LLMAdapter(Protocol):
    """Streaming LLM interface."""
    
    async def send_message(self, messages: list[LLMMessage], tools: list[dict] | None = None,
                          reasoning_effort: str | None = None) -> None:
        """Send a conversation turn to the LLM."""
        ...
    
    async def receive_tokens(self) -> AsyncIterator[str]:
        """Receive streaming response tokens."""
        ...
    
    async def receive_tool_calls(self) -> list[dict[str, Any]]:
        """Receive tool calls from the LLM."""
        ...
    
    async def close(self) -> None:
        """Close the LLM connection."""
        ...


class TTSAdapter(Protocol):
    """Streaming text-to-speech interface."""
    
    async def send_text(self, text: str, voice: str | None = None) -> None:
        """Send text for synthesis."""
        ...
    
    async def receive_audio(self) -> TTSChunk | None:
        """Receive synthesized audio chunks. None on stream end."""
        ...
    
    async def flush(self) -> None:
        """Flush any buffered audio."""
        ...
    
    async def close(self) -> None:
        """Close the TTS connection."""
        ...
