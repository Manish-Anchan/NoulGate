"""
NoulGate Core Engine
====================
Uses TypeSafe AI's Jev (System One) model to intelligently prune MCP tool
lists before they reach the LLM, reducing context bloat and tool-confusion
hallucinations.

Flow
----
1. User prompt arrives.
2. Pass 1 (Jev): Noul — does this need a tool at all?
               + Choice — which domain (database, github, filesystem, …)?
3. If tool is needed and the domain has >1 tool:
   Pass 2 (Jev): Choice — which exact tool?
4. Return PruneResult with the 0–N selected tools + full metrics.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from typesafe_sdk import Choice, Noul, TypeSafeClient


# ---------------------------------------------------------------------------
# ToolDefinition
# ---------------------------------------------------------------------------


@dataclass
class ToolDefinition:
    """
    Represents a single MCP tool that can be registered with NoulGate.

    Attributes:
        name:        Unique tool identifier (e.g. ``"sql_query_runner"``).
        description: Human-readable description used for Jev routing.
        parameters:  JSON-Schema-style parameters dict (OpenAI format).
        domain:      High-level group this tool belongs to
                     (e.g. ``"database"``, ``"github"``, ``"filesystem"``).
    """

    name: str
    description: str
    parameters: dict[str, Any]
    domain: str

    def estimate_tokens(self) -> int:
        """
        Rough token estimate for this tool's full schema.

        Uses a conservative 4-chars-per-token heuristic so we never need
        to import a full tokenizer as a dependency.
        """
        schema = json.dumps(
            {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
            separators=(",", ":"),
        )
        return max(1, len(schema) // 4)

    def to_openai_schema(self) -> dict[str, Any]:
        """Return this tool in OpenAI ``tools`` array format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------------------------------------------------------------------------
# PruneResult
# ---------------------------------------------------------------------------


@dataclass
class PruneResult:
    """
    The output of :meth:`NoulGateEngine.prune`.

    Attributes:
        needs_tool:          Whether Jev decided a tool is required.
        tool_probability:    Raw Noul probability (0.0 – 1.0).
        selected_domain:     The MCP server domain Jev routed to (or ``None``).
        selected_tools:      The pruned list of tools to forward to the LLM.
        total_tools_input:   How many tools were evaluated.
        total_tokens_input:  Estimated tokens for ALL tool schemas.
        pruned_tokens_output:Estimated tokens for the selected tools only.
        latency_ms:          End-to-end Jev decision time in milliseconds.
    """

    needs_tool: bool
    tool_probability: float
    selected_domain: str | None
    selected_tools: list[ToolDefinition]
    total_tools_input: int
    total_tokens_input: int
    pruned_tokens_output: int
    latency_ms: float

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def token_savings(self) -> int:
        """Absolute number of tokens saved vs. sending all schemas."""
        return self.total_tokens_input - self.pruned_tokens_output

    @property
    def token_savings_pct(self) -> float:
        """Token savings as a percentage (0–100)."""
        if self.total_tokens_input == 0:
            return 0.0
        return (self.token_savings / self.total_tokens_input) * 100.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Return the pruned tool list in OpenAI ``tools`` array format."""
        return [t.to_openai_schema() for t in self.selected_tools]

    def summary(self) -> str:
        """One-line human-readable summary of the routing decision."""
        if not self.needs_tool:
            return (
                f"⚡ No tool needed  (p={self.tool_probability:.2f})"
                f" — saved all {self.total_tokens_input} tool-schema tokens"
                f" in {self.latency_ms:.0f}ms"
            )
        names = [t.name for t in self.selected_tools]
        return (
            f"🎯 Tool needed     (p={self.tool_probability:.2f})"
            f" → domain={self.selected_domain!r}"
            f" → tools={names}"
            f" | saved {self.token_savings} tokens"
            f" ({self.token_savings_pct:.0f}%)"
            f" in {self.latency_ms:.0f}ms"
        )


# ---------------------------------------------------------------------------
# NoulGateEngine
# ---------------------------------------------------------------------------


class NoulGateEngine:
    """
    The NoulGate decision engine.

    Wraps TypeSafe AI's Jev (System One) model to evaluate user prompts
    and return the minimal set of MCP tools the downstream LLM actually needs.

    Example::

        from noulgate.engine import NoulGateEngine, ToolDefinition

        engine = NoulGateEngine()

        engine.register(
            ToolDefinition(
                name="sql_query_runner",
                description="Runs a read-only SQL query against Postgres.",
                parameters={"query": {"type": "string"}},
                domain="database",
            ),
            domain_criteria="SQL, Postgres, querying tables, revenue, user counts",
        )

        result = engine.prune("What was total revenue last week?")
        print(result.summary())
    """

    def __init__(
        self,
        client: TypeSafeClient | None = None,
        tool_threshold: float = 0.40,
    ) -> None:
        """
        Args:
            client:         TypeSafe SDK client. If ``None``, auto-initialises
                            from the ``TYPESAFE_API_KEY`` environment variable.
            tool_threshold: Minimum Noul probability required to conclude that
                            a tool is needed.  Default ``0.40`` is intentionally
                            conservative — when Jev is uncertain it is cheaper to
                            include a few extra tools than to miss a required one.
        """
        self.client: TypeSafeClient = client or TypeSafeClient()
        self.tool_threshold: float = tool_threshold

        self._tools: dict[str, ToolDefinition] = {}
        self._domain_criteria: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        tool: ToolDefinition,
        domain_criteria: str = "",
    ) -> None:
        """
        Register a single tool with the engine.

        Args:
            tool:            The tool to register.
            domain_criteria: Short rubric describing what queries belong to this
                             domain.  Only needed once per domain; subsequent
                             calls for the same domain are ignored unless
                             ``domain_criteria`` is non-empty (which updates it).
        """
        self._tools[tool.name] = tool
        if tool.domain not in self._domain_criteria:
            self._domain_criteria[tool.domain] = (
                domain_criteria or f"Tools related to {tool.domain}"
            )
        elif domain_criteria:
            self._domain_criteria[tool.domain] = domain_criteria

    def register_many(
        self,
        tools: list[ToolDefinition],
        domain_criteria: dict[str, str] | None = None,
    ) -> None:
        """
        Register multiple tools at once.

        Args:
            tools:           List of tool definitions.
            domain_criteria: Optional mapping of ``{domain: criteria_string}``.
        """
        for tool in tools:
            criteria = (domain_criteria or {}).get(tool.domain, "")
            self.register(tool, criteria)

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def prune(
        self,
        prompt: str,
        tools: list[ToolDefinition] | None = None,
    ) -> PruneResult:
        """
        Evaluate *prompt* and return only the tools the LLM actually needs.

        This is the primary method callers use.  Pass it the raw user message
        and optionally a per-request tool list (overrides the registered tools).

        Args:
            prompt: The user's message / agent turn.
            tools:  Optional per-request tool list. If ``None``, all registered
                    tools are used.

        Returns:
            :class:`PruneResult` containing the selected tools and metrics.
        """
        active_tools: dict[str, ToolDefinition] = (
            {t.name: t for t in tools} if tools is not None else self._tools
        )
        total_tokens = sum(t.estimate_tokens() for t in active_tools.values())

        # Edge case: nothing registered
        if not active_tools:
            return PruneResult(
                needs_tool=False,
                tool_probability=0.0,
                selected_domain=None,
                selected_tools=[],
                total_tools_input=0,
                total_tokens_input=0,
                pruned_tokens_output=0,
                latency_ms=0.0,
            )

        # Build domain map from currently active tools
        domain_map: dict[str, str] = {}
        for t in active_tools.values():
            if t.domain not in domain_map:
                domain_map[t.domain] = self._domain_criteria.get(
                    t.domain, f"Tools related to {t.domain}"
                )

        t0 = time.perf_counter()

        # ── Pass 1 ──────────────────────────────────────────────────────────
        # Parallel Noul + Choice in a single Jev forward pass (~70–150 ms).
        pass1 = self.client.system_one(
            state=f"User prompt: {prompt}",
            questions={
                "needs_tool": Noul(
                    instructions=(
                        "Does answering this prompt require calling an external "
                        "tool, fetching live data, querying a database, reading "
                        "a file, or interacting with an external API or service?"
                    )
                ),
                "target_domain": Choice(
                    instructions=(
                        "Which tool domain best matches what this prompt needs?"
                    ),
                    criteria=domain_map,
                ),
            },
        )

        tool_prob: float = pass1.answers["needs_tool"].noul
        chosen_domain: str = pass1.answers["target_domain"].choice

        # ── No-tool path ─────────────────────────────────────────────────────
        if tool_prob < self.tool_threshold:
            return PruneResult(
                needs_tool=False,
                tool_probability=tool_prob,
                selected_domain=None,
                selected_tools=[],
                total_tools_input=len(active_tools),
                total_tokens_input=total_tokens,
                pruned_tokens_output=0,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # ── Tool path: narrow down to the right domain ────────────────────────
        domain_tools = [t for t in active_tools.values() if t.domain == chosen_domain]

        if not domain_tools:
            # Domain matched but no tools found — fallback to all tools
            selected = list(active_tools.values())

        elif len(domain_tools) == 1:
            # Only one candidate — skip the second Jev call entirely
            selected = domain_tools

        else:
            # ── Pass 2 ────────────────────────────────────────────────────────
            # Drill down to the single best tool within the domain.
            pass2 = self.client.system_one(
                state=f"User prompt: {prompt}",
                questions={
                    "specific_tool": Choice(
                        instructions=(
                            "Select the single best tool to fulfill this prompt."
                        ),
                        criteria={t.name: t.description for t in domain_tools},
                    )
                },
            )
            best_name: str = pass2.answers["specific_tool"].choice
            selected = [active_tools[best_name]]

        pruned_tokens = sum(t.estimate_tokens() for t in selected)

        return PruneResult(
            needs_tool=True,
            tool_probability=tool_prob,
            selected_domain=chosen_domain,
            selected_tools=selected,
            total_tools_input=len(active_tools),
            total_tokens_input=total_tokens,
            pruned_tokens_output=pruned_tokens,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
