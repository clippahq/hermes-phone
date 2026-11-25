"""Factory to create call sessions based on configuration.

Chooses between OpenAI Realtime session and adapter-based session based on environment config.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..adapters.deepgram import DeepgramSTTAdapter
from ..adapters.elevenlabs import ElevenLabsTTSAdapter
from ..adapters.twilio import TwilioTelephonyAdapter
from ..adapters.xai import XAILLMAdapter
from ..store import Store
from . import realtime as rt
from .adapter_session import AdapterCallSession
from .session import CallSession
from .settings import BridgeSettings

if TYPE_CHECKING:
    from ..adapters import LLMAdapter, STTAdapter, TTSAdapter, TelephonyAdapter

log = logging.getLogger(__name__)


def get_session_mode(environ: dict[str, str] | None = None) -> str:
    """Get the configured session mode: 'realtime' or 'adapters'."""
    env = environ or os.environ
    return env.get("HERMES_PHONE_SESSION_MODE", "realtime")


async def create_call_session(
    *,
    ws: Any,
    call: dict,
    store: Store,
    settings: BridgeSettings,
    twilio_client_factory: Callable[[], Any],
    clock: Callable[[], float],
    environ: dict[str, str] | None = None,
) -> CallSession | AdapterCallSession:
    """Create a call session based on configuration.
    
    Environment variables:
        HERMES_PHONE_SESSION_MODE: "realtime" (default) or "adapters"
        
        For adapters mode:
            DEEPGRAM_API_KEY: Deepgram API key
            STT_LANGUAGE: Language for STT ("multi", "ar-SA", "ar-AE", "ar", "en")
            XAI_API_KEY: xAI API key
            LLM_MODEL: xAI model ("grok-4.3", "grok-4.7")
            LLM_REASONING_EFFORT: Reasoning effort ("none", "low", "medium", "high", "xhigh")
            ELEVENLABS_API_KEY: ElevenLabs API key
            TTS_VOICE: ElevenLabs voice ID
            
        For realtime mode:
            OPENAI_API_KEY: OpenAI API key (existing)
    """
    env = environ or os.environ
    mode = get_session_mode(env)
    
    if mode == "adapters":
        log.info("Creating adapter-based call session for %s", call["id"])
        
        # Create adapters
        stt_adapter = await _create_stt_adapter(env)
        llm_adapter = _create_llm_adapter(env)
        tts_adapter = await _create_tts_adapter(env)
        telephony_adapter = _create_telephony_adapter(ws, call)
        
        return AdapterCallSession(
            ws=ws,
            call=call,
            store=store,
            settings=settings,
            stt_adapter=stt_adapter,
            llm_adapter=llm_adapter,
            tts_adapter=tts_adapter,
            telephony_adapter=telephony_adapter,
            twilio_client_factory=twilio_client_factory,
            clock=clock,
        )
    else:
        log.info("Creating OpenAI Realtime call session for %s", call["id"])
        return CallSession(
            ws=ws,
            call=call,
            store=store,
            settings=settings,
            connect=rt.connect,
            twilio_client_factory=twilio_client_factory,
            clock=clock,
        )


async def _create_stt_adapter(env: dict[str, str]) -> STTAdapter:
    """Create and initialize STT adapter."""
    api_key = env.get("DEEPGRAM_API_KEY", "")
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY is required for adapters mode")
    
    language = env.get("STT_LANGUAGE", "multi")
    model = env.get("STT_MODEL", "nova-3")
    endpointing_ms = int(env.get("STT_ENDPOINTING_MS", "300"))
    
    adapter = DeepgramSTTAdapter(
        api_key=api_key,
        language=language,
        model=model,
        endpointing_ms=endpointing_ms,
        environ=env,
    )
    
    # Connect to Deepgram
    await adapter.connect()
    return adapter


def _create_llm_adapter(env: dict[str, str]) -> LLMAdapter:
    """Create LLM adapter."""
    api_key = env.get("XAI_API_KEY", "")
    if not api_key:
        raise ValueError("XAI_API_KEY is required for adapters mode")
    
    model = env.get("LLM_MODEL", "grok-4.3")
    reasoning_effort = env.get("LLM_REASONING_EFFORT", "none")
    temperature = float(env.get("LLM_TEMPERATURE", "0.7"))
    
    return XAILLMAdapter(
        api_key=api_key,
        model=model,
        reasoning_effort=reasoning_effort,
        temperature=temperature,
        environ=env,
    )


async def _create_tts_adapter(env: dict[str, str]) -> TTSAdapter:
    """Create and initialize TTS adapter."""
    api_key = env.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is required for adapters mode")
    
    voice = env.get("TTS_VOICE", "")
    if not voice:
        raise ValueError("TTS_VOICE is required for adapters mode")
    
    model = env.get("TTS_MODEL", "eleven_flash_v2_5")
    
    adapter = ElevenLabsTTSAdapter(
        api_key=api_key,
        voice=voice,
        model=model,
        environ=env,
    )
    
    # Connect to ElevenLabs
    await adapter.connect()
    return adapter


def _create_telephony_adapter(ws: Any, call: dict) -> TelephonyAdapter:
    """Create telephony adapter."""
    return TwilioTelephonyAdapter(
        ws=ws,
        stream_sid=call.get("provider_sid", ""),
    )
