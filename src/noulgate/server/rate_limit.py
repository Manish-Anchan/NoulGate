"""
noulgate.server.rate_limit
==========================
In-memory daily IP rate limiter for NoulGate's free tier.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

# Default: 50 requests per day per IP for free tier (override via env)
FREE_TIER_DAILY_LIMIT: int = int(os.getenv("FREE_TIER_DAILY_LIMIT", "50"))

_rate_store: dict[str, dict[str, Any]] = defaultdict(lambda: {"date": "", "count": 0})
_rate_lock = threading.Lock()


def today_utc() -> str:
    """Return current UTC date formatted as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_rate_limit(ip: str) -> tuple[bool, int]:
    """
    Check and increment the daily request counter for *ip*.

    Returns:
        (is_allowed, remaining_quota)
    """
    today = today_utc()
    with _rate_lock:
        rec = _rate_store[ip]
        if rec["date"] != today:  # new day — reset counter
            rec["date"] = today
            rec["count"] = 0
        if rec["count"] >= FREE_TIER_DAILY_LIMIT:
            return False, 0
        rec["count"] += 1
        return True, FREE_TIER_DAILY_LIMIT - rec["count"]


def rate_limit_headers(remaining: int | str) -> dict[str, str]:
    """Generate standard rate limit response headers."""
    return {
        "X-RateLimit-Limit": str(FREE_TIER_DAILY_LIMIT),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": today_utc(),
        "X-NoulGate-Version": "0.1.0",
    }
