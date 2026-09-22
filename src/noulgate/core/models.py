"""
noulgate.core.models
====================
Data structures and models for NoulGate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    """
    Representation of an MCP or OpenAI tool schema.

    Attributes:
        name: Unique tool identifier (e.g. ``"sql_query_runner"``).
        description: Plain English description of the tool's purpose.
        parameters: JSON Schema dict defining the tool's input arguments.
        domain: Functional category (e.g. ``"database"``, ``"github"``).
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    domain: str = "general"

    def estimated_tokens(self) -> int:
        """Estimate the token footprint of this tool schema."""
        raw = json.dumps(self.to_openai_schema())
        return max(1, len(raw) // 4)

    estimate_tokens = estimated_tokens  # backwards compatibility alias

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class PruneResult:
    """
    Result returned by :meth:`NoulGateEngine.prune`.

    Attributes:
        needs_tool: True if Jev determined a tool is required for this query.
        tool_probability: Raw Noul probability (0.0 to 1.0).
        selected_domain: The domain chosen during Pass 1, or None.
        selected_tools: The subset of ToolDefinitions selected for the prompt.
        total_tools_input: How many tools were evaluated.
        total_tokens_input: Estimated tokens for all tools before pruning.
        pruned_tokens_output: Estimated tokens for selected tools only.
        latency_ms: Total time taken by Jev passes.
    """

    needs_tool: bool
    tool_probability: float
    selected_domain: str | None
    selected_tools: list[ToolDefinition]
    total_tools_input: int
    total_tokens_input: int
    pruned_tokens_output: int
    latency_ms: float

    @property
    def token_savings(self) -> int:
        """Tokens saved compared to sending all tools."""
        return max(0, self.total_tokens_input - self.pruned_tokens_output)

    @property
    def token_savings_pct(self) -> float:
        """Percentage of tool-schema tokens saved."""
        if self.total_tokens_input == 0:
            return 0.0
        return (self.token_savings / self.total_tokens_input) * 100.0

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Return the selected tools formatted for OpenAI API."""
        return [t.to_openai_schema() for t in self.selected_tools]

    def summary(self) -> str:
        """One-line human-readable summary of the pruning decision."""
        if not self.needs_tool:
            return (
                f"⚡ No tool needed  (p={self.tool_probability:.2f}) — "
                f"saved all {self.total_tokens_input} tool-schema tokens "
                f"in {self.latency_ms:.0f}ms"
            )
        tool_names = [t.name for t in self.selected_tools]
        return (
            f"🎯 Tool needed     (p={self.tool_probability:.2f}) → "
            f"domain='{self.selected_domain}' → tools={tool_names} | "
            f"saved {self.token_savings} tokens "
            f"({self.token_savings_pct:.0f}%) in {self.latency_ms:.0f}ms"
        )
