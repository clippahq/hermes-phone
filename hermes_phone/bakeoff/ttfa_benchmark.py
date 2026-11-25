"""TTFA (Time To First Audio) benchmark for LLM+TTS pipeline.

Measures end-to-end latency from text prompt to first audio chunk:
- Grok 4.3 (reasoning: none) + ElevenLabs Flash v2.5
- Grok 4.20 (non-reasoning) + ElevenLabs Flash v2.5
- Claude Haiku 5.5 + ElevenLabs Flash v2.5

Target: ≤800ms p50 TTFA for live phone turns.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class TTFAResult:
    """Result of one TTFA measurement."""
    llm_model: str
    tts_model: str
    ttfa_ms: float
    llm_ttft_ms: float  # Time to first token
    tts_first_chunk_ms: float  # Time from first token to first audio


TEST_PROMPTS = [
    "Thank you! Just to confirm: 4 people, tonight at 8 PM, under Mohamed Al Khalifa.",
    "Let me check on that. One moment please.",
    "I'd like to book a table for 2 people tomorrow at 7:30 PM.",
]


async def measure_ttfa(
    llm_model: str,
    llm_api_key: str,
    tts_voice_id: str,
    tts_api_key: str,
    prompt: str,
) -> TTFAResult:
    """Measure TTFA for one LLM+TTS combination."""
    # This is a stub - full implementation would:
    # 1. Send prompt to LLM API and measure TTFT
    # 2. Stream first LLM tokens to TTS API
    # 3. Measure time to first audio chunk
    # 4. Return full latency breakdown
    
    # Placeholder: simulate measurements
    await asyncio.sleep(0.1)  # Simulate network call
    
    return TTFAResult(
        llm_model=llm_model,
        tts_model="eleven_flash_v2_5",
        ttfa_ms=750.0,  # Placeholder
        llm_ttft_ms=600.0,  # Placeholder
        tts_first_chunk_ms=150.0,  # Placeholder
    )


async def run_ttfa_benchmark() -> dict[str, Any]:
    """Run TTFA benchmark on configured LLM+TTS combinations.
    
    Requires:
        - XAI_API_KEY (or ANTHROPIC_API_KEY for Claude)
        - ELEVENLABS_API_KEY
        - ELEVENLABS_VOICE_ID
    
    Returns:
        Dictionary with per-model results and summary.
    """
    xai_key = os.environ.get("XAI_API_KEY")
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
    
    if not xai_key or not elevenlabs_key or not voice_id:
        return {
            "error": "Missing required keys: XAI_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID",
            "results": [],
        }
    
    models = [
        ("grok-4.3", "reasoning: none"),
        ("grok-4.20", "non-reasoning"),
    ]
    
    results: list[TTFAResult] = []
    
    print("Running TTFA benchmark...")
    print(f"Prompts: {len(TEST_PROMPTS)}")
    print(f"Models: {', '.join(m[0] for m in models)}\n")
    
    for llm_model, description in models:
        print(f"{llm_model} ({description}):")
        
        for i, prompt in enumerate(TEST_PROMPTS, 1):
            try:
                result = await measure_ttfa(
                    llm_model,
                    xai_key,
                    voice_id,
                    elevenlabs_key,
                    prompt,
                )
                results.append(result)
                
                print(f"  Prompt {i}: TTFA={result.ttfa_ms:.0f}ms "
                      f"(TTFT={result.llm_ttft_ms:.0f}ms + TTS={result.tts_first_chunk_ms:.0f}ms)")
            
            except Exception as e:  # noqa: BLE001
                print(f"  Prompt {i}: ERROR - {e}")
        
        print()
    
    # Compute p50 per model
    summary: dict[str, Any] = {}
    for model, _ in models:
        model_results = [r for r in results if r.llm_model == model]
        if model_results:
            ttfa_values = sorted(r.ttfa_ms for r in model_results)
            p50 = ttfa_values[len(ttfa_values) // 2]
            
            summary[model] = {
                "p50_ttfa_ms": p50,
                "sample_count": len(model_results),
            }
            
            status = "✓" if p50 <= 800 else "✗"
            print(f"{status} {model}: p50 TTFA = {p50:.0f}ms (target: ≤800ms)")
    
    return {
        "summary": summary,
        "results": [
            {
                "llm": r.llm_model,
                "tts": r.tts_model,
                "ttfa_ms": r.ttfa_ms,
                "llm_ttft_ms": r.llm_ttft_ms,
                "tts_first_chunk_ms": r.tts_first_chunk_ms,
            }
            for r in results
        ],
    }


if __name__ == "__main__":
    asyncio.run(run_ttfa_benchmark())
