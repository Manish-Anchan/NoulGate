"""
noulgate.server
===============
FastAPI reverse proxy server, rate limiting, and dynamic routing.
"""

from noulgate.server.app import app, create_app
from noulgate.server.rate_limit import (
    FREE_TIER_DAILY_LIMIT,
    check_rate_limit,
    rate_limit_headers,
)
from noulgate.server.router import (
    PROVIDER_PRESETS,
    UPSTREAM_BASE_URL,
    resolve_upstream_base_url,
)

__all__ = [
    "app",
    "create_app",
    "check_rate_limit",
    "rate_limit_headers",
    "FREE_TIER_DAILY_LIMIT",
    "resolve_upstream_base_url",
    "UPSTREAM_BASE_URL",
    "PROVIDER_PRESETS",
]
