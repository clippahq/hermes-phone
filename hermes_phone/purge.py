"""30-day transcript auto-purge for Bahrain PDPL compliance (Law No. 30 of 2018).

Automatically deletes verbatim transcript_text older than 30 days, retaining only
anonymized booking/cost metrics for reliability tracking.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .store import Store

log = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 30


def purge_old_transcripts(
    store: Store,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
) -> dict[str, int]:
    """Purge transcripts older than retention_days.
    
    Args:
        store: Call store with transcript data
        retention_days: Number of days to retain transcripts (default: 30)
        dry_run: If True, only count what would be purged (no deletion)
    
    Returns:
        Dictionary with purge statistics:
        - calls_checked: Total calls examined
        - transcripts_purged: Number of transcript rows deleted
        - oldest_purged_days: Age of oldest purged transcript
    """
    now = store.clock()
    cutoff = now - (retention_days * 86400)  # 86400 seconds = 1 day
    
    # Find calls older than cutoff
    calls = store.conn.execute(
        "SELECT id, created_at FROM calls WHERE created_at < ?",
        (cutoff,)
    ).fetchall()
    
    calls_checked = len(calls)
    transcripts_purged = 0
    oldest_purged_days = 0
    
    if not calls:
        return {
            "calls_checked": 0,
            "transcripts_purged": 0,
            "oldest_purged_days": 0,
        }
    
    oldest_ts = min(c["created_at"] for c in calls)
    oldest_purged_days = int((now - oldest_ts) / 86400)
    
    if dry_run:
        # Count transcripts that would be deleted
        for call_row in calls:
            count = store.conn.execute(
                "SELECT COUNT(*) AS n FROM transcripts WHERE call_id = ?",
                (call_row["id"],)
            ).fetchone()
            transcripts_purged += count["n"] if count else 0
    else:
        # Actually delete transcripts
        for call_row in calls:
            result = store.conn.execute(
                "DELETE FROM transcripts WHERE call_id = ?",
                (call_row["id"],)
            )
            transcripts_purged += result.rowcount
        
        store.conn.commit()
        log.info(
            "Purged %d transcript rows from %d calls older than %d days",
            transcripts_purged,
            calls_checked,
            retention_days,
        )
    
    return {
        "calls_checked": calls_checked,
        "transcripts_purged": transcripts_purged,
        "oldest_purged_days": oldest_purged_days,
    }


def purge_call_transcript(store: Store, call_id: str) -> bool:
    """Purge transcripts for a specific call immediately.
    
    Args:
        store: Call store
        call_id: ID of the call whose transcripts should be purged
    
    Returns:
        True if transcripts were deleted, False if call not found or no transcripts
    """
    # Check if call exists
    call = store.get_call(call_id)
    if not call:
        return False
    
    # Delete transcripts
    result = store.conn.execute(
        "DELETE FROM transcripts WHERE call_id = ?",
        (call_id,)
    )
    store.conn.commit()
    
    deleted = result.rowcount > 0
    if deleted:
        log.info("Purged %d transcript rows for call %s", result.rowcount, call_id)
    
    return deleted


def purge_all_transcripts(store: Store) -> int:
    """Purge ALL transcripts immediately (for /phone purge --all).
    
    WARNING: This deletes all stored transcripts regardless of age.
    
    Args:
        store: Call store
    
    Returns:
        Number of transcript rows deleted
    """
    result = store.conn.execute("DELETE FROM transcripts")
    store.conn.commit()
    
    deleted = result.rowcount
    log.warning("Purged ALL transcripts: %d rows deleted", deleted)
    
    return deleted
