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
    print(result.to_openai_tools())  # pass directly to openai.chat.completions
"""

from noulgate.engine import NoulGateEngine, PruneResult, ToolDefinition

__all__ = ["NoulGateEngine", "ToolDefinition", "PruneResult"]
__version__ = "0.1.0"
