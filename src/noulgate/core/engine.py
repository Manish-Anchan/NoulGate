"""
noulgate.core.engine
====================
Core decision and pruning engine powered by TypeSafe AI's Jev model.
"""

from __future__ import annotations

import time
from typing import Any

from typesafe_sdk import Choice, Noul, TypeSafeClient

from noulgate.core.models import PruneResult, ToolDefinition


class NoulGateEngine:
    """
    The NoulGate decision engine.

    Wraps TypeSafe AI's Jev (System One) model to evaluate user prompts
    and return the minimal set of MCP tools the downstream LLM actually needs.
    """

    def __init__(
        self,
        client: TypeSafeClient | None = None,
        tool_threshold: float = 0.28,
    ) -> None:
        """
        Args:
            client: TypeSafe SDK client. If None, auto-initialises from TYPESAFE_API_KEY.
            tool_threshold: Minimum Noul probability required to conclude a tool is needed.
        """
        self.client: TypeSafeClient = client or TypeSafeClient()
        self.tool_threshold: float = tool_threshold
        self._tools: dict[str, ToolDefinition] = {}
        self._domain_criteria: dict[str, str] = {}

    def register(
        self,
        tool: ToolDefinition,
        domain_criteria: str = "",
    ) -> None:
        """Register a single tool with the engine."""
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
        """Register multiple tools at once."""
        for tool in tools:
            criteria = domain_criteria.get(tool.domain, "") if domain_criteria else ""
            self.register(tool, domain_criteria=criteria)

    def prune(
        self,
        prompt: str,
        tools: list[ToolDefinition] | None = None,
    ) -> PruneResult:
        """
        Evaluate a user prompt and prune the tool set strictly among provided tools.

        Pass 1: Parallel Noul (tool needed?) + Choice (target domain).
        Pass 2: Select matching domain toolset (or top tool if domain > 5).
        """
        active_tools = (
            {t.name: t for t in tools} if tools is not None else self._tools
        )
        total_tokens = sum(t.estimated_tokens() for t in active_tools.values())

        # Edge case: no tools provided
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

        # Build domain criteria map only from the active tools provided by caller
        domain_map: dict[str, str] = {}
        for t in active_tools.values():
            if t.domain not in domain_map:
                domain_map[t.domain] = self._domain_criteria.get(
                    t.domain, f"Tools related to {t.domain}"
                )

        t0 = time.perf_counter()

        # ── Pass 1: Parallel Noul for tool need + all candidate domains ───────
        pass1_questions: dict[str, Any] = {
            "needs_tool": Noul(
                instructions=(
                    "Does answering this prompt require calling an external tool, "
                    "searching the live web for recent technologies, documentation, products, sports fixtures, or live data, "
                    "querying real-time system metrics, querying a database, or accessing files/APIs?"
                )
            ),
        }
        for d, criteria in domain_map.items():
            pass1_questions[f"dom_{d}"] = Noul(
                instructions=f"Does this prompt require tools or data from {d}? ({criteria})"
            )

        pass1 = self.client.system_one(
            state=f"User prompt: {prompt}",
            questions=pass1_questions,
        )

        tool_prob: float = pass1.answers["needs_tool"].noul

        # ── Path A: No tool needed (p < threshold) ───────────────────────────
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

        # ── Path B: Tool needed — high-confidence multi-domain selection ─────
        # Find best domain and any co-occurring high-confidence domains (>= 0.80)
        domain_scores = {
            d: pass1.answers[f"dom_{d}"].noul for d in domain_map
        }
        best_domain = max(domain_scores.keys(), key=lambda d: domain_scores[d])

        candidate_domains = [best_domain]
        for d, score in domain_scores.items():
            if d != best_domain and score >= 0.80:
                candidate_domains.append(d)

        # Gather tools across all selected domains
        selected: list[ToolDefinition] = []
        for d in candidate_domains:
            d_tools = [t for t in active_tools.values() if t.domain == d]
            if len(d_tools) <= 5:
                for t in d_tools:
                    if not any(st.name == t.name for st in selected):
                        selected.append(t)
            else:
                # If a specific domain has >5 tools, select the best matching tool
                pass2 = self.client.system_one(
                    state=f"User prompt: {prompt}",
                    questions={
                        "specific_tool": Choice(
                            instructions=f"Select the single best tool from {d} to fulfill this prompt.",
                            criteria={t.name: t.description for t in d_tools},
                        )
                    },
                )
                best_name: str = pass2.answers["specific_tool"].choice
                tool_match = active_tools.get(best_name) or d_tools[0]
                if not any(st.name == tool_match.name for st in selected):
                    selected.append(tool_match)

        if not selected:
            selected = list(active_tools.values())

        selected_domain_str = ", ".join(candidate_domains)
        pruned_tokens = sum(t.estimated_tokens() for t in selected)

        return PruneResult(
            needs_tool=True,
            tool_probability=tool_prob,
            selected_domain=selected_domain_str,
            selected_tools=selected,
            total_tools_input=len(active_tools),
            total_tokens_input=total_tokens,
            pruned_tokens_output=pruned_tokens,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
