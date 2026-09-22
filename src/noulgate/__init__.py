"""
NoulGate
========
A high-speed System 1 gateway that prunes MCP tool bloat using
TypeSafe AI's Jev model before it reaches your LLM.

Quick start::

    from noulgate import NoulGateEngine, ToolDefinition

    engine = NoulGateEngine()
    engine.register(
        ToolDefinition(
            name="sql_query_runner",
            description="Runs a read-only SQL query against Postgres.",
            parameters={"query": {"type": "string"}},
            domain="database",
        ),
        domain_criteria="SQL, Postgres, revenue, user counts, tables",
    )

    result = engine.prune("What was total revenue last week?")
    print(result.summary())
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

# Optional server exports (only loaded if fastapi is installed)
try:
    from noulgate.server import app, create_app
except ImportError:
    app = None        # type: ignore[assignment]
    create_app = None  # type: ignore[assignment]

__all__ = [
    "NoulGateEngine",
    "ToolDefinition",
    "PruneResult",
    "app",
    "create_app",
    "infer_domain",
    "openai_tools_to_definitions",
    "extract_prompt",
    "DEFAULT_DOMAIN_CRITERIA",
    "DOMAIN_PATTERNS",
]
__version__ = "0.1.0"
