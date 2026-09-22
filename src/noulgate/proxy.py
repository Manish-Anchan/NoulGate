"""
noulgate.proxy
==============
Backwards-compatibility module forwarding to noulgate.server and noulgate.core.
"""

from noulgate.core import (
    DEFAULT_DOMAIN_CRITERIA,
    DOMAIN_PATTERNS,
    NoulGateEngine,
    PruneResult,
    ToolDefinition,
    extract_prompt,
    infer_domain,
    openai_tools_to_definitions,
)
from noulgate.server import (
    FREE_TIER_DAILY_LIMIT,
    PROVIDER_PRESETS,
    UPSTREAM_BASE_URL,
    app,
    check_rate_limit,
    create_app,
    rate_limit_headers,
    resolve_upstream_base_url,
)

# Legacy private aliases for test scripts and backward compatibility
_infer_domain = infer_domain
_openai_tools_to_definitions = openai_tools_to_definitions
_extract_prompt = extract_prompt
_check_rate_limit = check_rate_limit
_rate_limit_headers = rate_limit_headers
_DOMAIN_PATTERNS = DOMAIN_PATTERNS
_DOMAIN_CRITERIA = DEFAULT_DOMAIN_CRITERIA

__all__ = [
    "app",
    "create_app",
    "NoulGateEngine",
    "ToolDefinition",
    "PruneResult",
    "infer_domain",
    "resolve_upstream_base_url",
    "check_rate_limit",
    "rate_limit_headers",
    "FREE_TIER_DAILY_LIMIT",
    "PROVIDER_PRESETS",
    "UPSTREAM_BASE_URL",
]
