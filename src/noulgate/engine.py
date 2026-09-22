"""
noulgate.engine
===============
Backwards-compatibility module forwarding to noulgate.core.
"""

from noulgate.core import NoulGateEngine, PruneResult, ToolDefinition

__all__ = ["NoulGateEngine", "ToolDefinition", "PruneResult"]
