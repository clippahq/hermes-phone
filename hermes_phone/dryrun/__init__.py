"""Dry-run simulation harness for offline testing.

Runs 7 scripted restaurant-booking scenarios with mocked STT/LLM/TTS adapters.
All scenarios execute offline with no real API calls or PSTN dialing.
"""
from __future__ import annotations

from .harness import DryRunHarness, ScenarioResult
from .scenarios import SCENARIOS

__all__ = ["DryRunHarness", "ScenarioResult", "SCENARIOS"]
