"""Offline bake-off harness for STT and LLM+TTS benchmarking.

Compares Deepgram ar-SA/ar-AE/ar/multi on recorded Bahraini Arabic samples.
Requires explicit env keys and never runs in CI or tests.
"""
from __future__ import annotations

from .stt_benchmark import run_stt_bakeoff
from .ttfa_benchmark import run_ttfa_benchmark


__all__ = ["run_stt_bakeoff", "run_ttfa_benchmark"]
