"""
noulgate.core
=============
Core models, domain heuristics, and pruning engine.
"""

from noulgate.core.domains import (
    DEFAULT_DOMAIN_CRITERIA,
    DOMAIN_PATTERNS,
    extract_prompt,
    infer_domain,
    openai_tools_to_definitions,
)
from noulgate.core.engine import NoulGateEngine
from noulgate.core.models import PruneResult, ToolDefinition

__all__ = [
    "ToolDefinition",
    "PruneResult",
    "NoulGateEngine",
    "infer_domain",
    "openai_tools_to_definitions",
    "extract_prompt",
    "DEFAULT_DOMAIN_CRITERIA",
    "DOMAIN_PATTERNS",
]
