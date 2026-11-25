"""STT bake-off: Compare Deepgram ar-SA/ar-AE/ar/multi on Bahraini samples.

Computes Character Error Rate (CER) and Word Error Rate (WER) against reference transcripts.
Requires DEEPGRAM_API_KEY in environment and recorded samples in ./samples/ directory.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from jiwer import cer, wer
except ImportError:
    cer = None  # type: ignore[assignment]
    wer = None  # type: ignore[assignment]


@dataclass
class STTResult:
    """Result of one STT transcription."""
    language: str
    transcript: str
    cer_score: float
    wer_score: float
    latency_ms: float


@dataclass
class SampleFile:
    """One audio sample with reference transcript."""
    path: Path
    reference_text: str


SAMPLES_DIR = Path(__file__).parent / "samples"


def load_samples() -> list[SampleFile]:
    """Load audio samples and their reference transcripts."""
    samples: list[SampleFile] = []
    
    if not SAMPLES_DIR.exists():
        return samples
    
    for audio_file in SAMPLES_DIR.glob("*.wav"):
        # Look for corresponding .txt reference file
        txt_file = audio_file.with_suffix(".txt")
        if txt_file.exists():
            reference_text = txt_file.read_text(encoding="utf-8").strip()
            samples.append(SampleFile(path=audio_file, reference_text=reference_text))
    
    return samples


async def transcribe_with_deepgram(
    audio_path: Path,
    language: str,
    api_key: str,
) -> tuple[str, float]:
    """Transcribe audio file with Deepgram and return (transcript, latency_ms)."""
    import time
    
    import httpx
    
    start = time.time()
    
    url = "https://api.deepgram.com/v1/listen"
    params = {
        "model": "nova-3",
        "language": language,
    }
    
    if language == "multi":
        params["detect_language"] = "true"
        params["language_hint"] = "ar,en"
    
    headers = {"Authorization": f"Token {api_key}"}
    
    with open(audio_path, "rb") as f:
        audio_data = f.read()
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            params=params,
            headers=headers,
            content=audio_data,
        )
        response.raise_for_status()
        data = response.json()
    
    latency_ms = (time.time() - start) * 1000
    
    # Extract transcript
    results = data.get("results", {})
    channels = results.get("channels", [])
    if channels:
        alternatives = channels[0].get("alternatives", [])
        if alternatives:
            transcript = alternatives[0].get("transcript", "").strip()
            return transcript, latency_ms
    
    return "", latency_ms


async def run_stt_bakeoff() -> dict[str, Any]:
    """Run STT bake-off comparing Deepgram languages on all samples.
    
    Returns:
        Dictionary with results per language and summary statistics.
    """
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        return {
            "error": "DEEPGRAM_API_KEY not set. This benchmark requires explicit API key.",
            "languages": [],
            "samples": [],
        }
    
    if cer is None or wer is None:
        return {
            "error": "jiwer not installed. Run: pip install jiwer",
            "languages": [],
            "samples": [],
        }
    
    samples = load_samples()
    if not samples:
        return {
            "error": f"No samples found in {SAMPLES_DIR}. Add .wav files with .txt references.",
            "languages": [],
            "samples": [],
        }
    
    languages = ["ar-SA", "ar-AE", "ar", "multi"]
    results: dict[str, list[STTResult]] = {lang: [] for lang in languages}
    
    print(f"Running STT bake-off on {len(samples)} samples...")
    print(f"Languages: {', '.join(languages)}\n")
    
    for sample in samples:
        print(f"Sample: {sample.path.name}")
        
        for language in languages:
            try:
                transcript, latency = await transcribe_with_deepgram(
                    sample.path,
                    language,
                    api_key,
                )
                
                cer_score = cer(sample.reference_text, transcript)
                wer_score = wer(sample.reference_text, transcript)
                
                result = STTResult(
                    language=language,
                    transcript=transcript,
                    cer_score=cer_score,
                    wer_score=wer_score,
                    latency_ms=latency,
                )
                results[language].append(result)
                
                print(f"  {language}: CER={cer_score:.2%}, WER={wer_score:.2%}, latency={latency:.0f}ms")
            
            except Exception as e:  # noqa: BLE001
                print(f"  {language}: ERROR - {e}")
        
        print()
    
    # Compute averages
    summary: dict[str, Any] = {}
    for language in languages:
        lang_results = results[language]
        if lang_results:
            avg_cer = sum(r.cer_score for r in lang_results) / len(lang_results)
            avg_wer = sum(r.wer_score for r in lang_results) / len(lang_results)
            avg_latency = sum(r.latency_ms for r in lang_results) / len(lang_results)
            
            summary[language] = {
                "avg_cer": avg_cer,
                "avg_wer": avg_wer,
                "avg_latency_ms": avg_latency,
                "sample_count": len(lang_results),
            }
            
            print(f"{language} Average: CER={avg_cer:.2%}, WER={avg_wer:.2%}, latency={avg_latency:.0f}ms")
    
    # Find best language by CER
    best_lang = min(summary.keys(), key=lambda k: summary[k]["avg_cer"])
    print(f"\nBest language by CER: {best_lang} ({summary[best_lang]['avg_cer']:.2%})")
    
    return {
        "summary": summary,
        "best_language": best_lang,
        "samples_tested": len(samples),
    }


if __name__ == "__main__":
    asyncio.run(run_stt_bakeoff())
