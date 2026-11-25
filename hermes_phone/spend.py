"""Daily spend and usage tracking with hard caps.

Atomic SQLite ledger tracking $/min/calls per Bahrain date (Asia/Bahrain timezone).
Enforces $6/day, 20 min/day, 10 calls/day defaults (configurable via env).
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .store import Store

BAHRAIN_TZ = ZoneInfo("Asia/Bahrain")

DEFAULT_MAX_DAILY_SPEND_USD = 6.0
DEFAULT_MAX_DAILY_MINUTES = 20.0
DEFAULT_MAX_DAILY_CALLS = 10

ENV_MAX_DAILY_SPEND = "HERMES_PHONE_MAX_DAILY_SPEND_USD"
ENV_MAX_DAILY_MINUTES = "HERMES_PHONE_MAX_DAILY_MINUTES"
ENV_MAX_DAILY_CALLS = "HERMES_PHONE_MAX_DAILY_CALLS"


@dataclass(frozen=True)
class SpendCheck:
    """Result of a spend limit check."""
    ok: bool
    reason: str = ""
    current_spend: float = 0.0
    current_minutes: float = 0.0
    current_calls: int = 0


OK_SPEND = SpendCheck(ok=True)


def _get_bahrain_date(now: datetime | None = None) -> str:
    """Return current Bahrain date in YYYY-MM-DD format."""
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    bahrain_time = now.astimezone(BAHRAIN_TZ)
    return bahrain_time.strftime("%Y-%m-%d")


def _get_limits(environ: Mapping[str, str] | None = None) -> tuple[float, float, int]:
    """Read spend limits from environment with fail-safe defaults."""
    env = os.environ if environ is None else environ

    try:
        max_spend = float(env.get(ENV_MAX_DAILY_SPEND, str(DEFAULT_MAX_DAILY_SPEND_USD)))
    except (ValueError, TypeError):
        max_spend = DEFAULT_MAX_DAILY_SPEND_USD

    try:
        max_minutes = float(env.get(ENV_MAX_DAILY_MINUTES, str(DEFAULT_MAX_DAILY_MINUTES)))
    except (ValueError, TypeError):
        max_minutes = DEFAULT_MAX_DAILY_MINUTES

    try:
        max_calls = int(env.get(ENV_MAX_DAILY_CALLS, str(DEFAULT_MAX_DAILY_CALLS)))
    except (ValueError, TypeError):
        max_calls = DEFAULT_MAX_DAILY_CALLS

    return max_spend, max_minutes, max_calls


def check_daily_limits(store: Store, estimated_cost_usd: float = 0.0,
                      estimated_minutes: float = 0.0,
                      environ: Mapping[str, str] | None = None,
                      now: datetime | None = None) -> SpendCheck:
    """Check if placing a new call would exceed daily limits.

    Args:
        store: Call store with today's spend data
        estimated_cost_usd: Estimated cost of the new call
        estimated_minutes: Estimated duration of the new call
        environ: Environment variables (None = os.environ)
        now: Current time (None = datetime.now(UTC))

    Returns:
        SpendCheck with ok=True if within limits, ok=False with reason otherwise
    """
    max_spend, max_minutes, max_calls = _get_limits(environ)
    bahrain_date = _get_bahrain_date(now)

    # Get today's totals from store
    today_calls = store.get_calls_by_bahrain_date(bahrain_date)

    current_spend = sum(c.get("cost_usd", 0.0) for c in today_calls)
    current_minutes = sum(c.get("duration_s", 0) / 60.0 for c in today_calls)
    current_calls = len(today_calls)

    # Check spend cap
    if current_spend + estimated_cost_usd >= max_spend:
        return SpendCheck(
            ok=False,
            reason=f"Daily spend cap reached (${current_spend:.2f} + ${estimated_cost_usd:.2f} "
                   f">= ${max_spend:.2f} limit for {bahrain_date}).",
            current_spend=current_spend,
            current_minutes=current_minutes,
            current_calls=current_calls
        )

    # Check minute cap
    if current_minutes + estimated_minutes >= max_minutes:
        return SpendCheck(
            ok=False,
            reason=f"Daily minutes cap reached ({current_minutes:.1f} + {estimated_minutes:.1f} "
                   f">= {max_minutes:.1f} min limit for {bahrain_date}).",
            current_spend=current_spend,
            current_minutes=current_minutes,
            current_calls=current_calls
        )

    # Check call count cap
    if current_calls >= max_calls:
        return SpendCheck(
            ok=False,
            reason=f"Daily call limit reached ({current_calls} calls today, "
                   f"max {max_calls} for {bahrain_date}).",
            current_spend=current_spend,
            current_minutes=current_minutes,
            current_calls=current_calls
        )

    return SpendCheck(
        ok=True,
        current_spend=current_spend,
        current_minutes=current_minutes,
        current_calls=current_calls
    )


def estimate_call_cost(duration_s: int, *,
                       twilio_per_min: float = 0.2267,
                       deepgram_per_min: float = 0.0145,
                       elevenlabs_per_min: float = 0.0360,
                       grok_per_min: float = 0.0120) -> float:
    """Estimate total call cost in USD based on duration and provider rates.

    Default rates for Bahrain calls:
    - Twilio: $0.2267/min (Bahrain outbound)
    - Deepgram Nova-3 multi: $0.0145/min
    - ElevenLabs Flash v2.5: $0.0360/min
    - Grok 4.3 non-reasoning: ~$0.0120/min

    Total: ~$0.2892/min or ~$0.0048/s
    """
    minutes = duration_s / 60.0
    return (twilio_per_min + deepgram_per_min + elevenlabs_per_min + grok_per_min) * minutes


def record_call_cost(store: Store, call_id: str, duration_s: int, cost_usd: float,
                    now: datetime | None = None) -> None:
    """Record the final cost and duration of a completed call."""
    bahrain_date = _get_bahrain_date(now)
    store.update_call(call_id,
                     duration_s=duration_s,
                     cost_usd=cost_usd,
                     bahrain_date=bahrain_date)
