"""
noulgate.core.domains
=====================
Domain inference heuristics, regex patterns, and message prompt extractors.
"""

from __future__ import annotations

import re
from typing import Any

from noulgate.core.models import ToolDefinition

# ---------------------------------------------------------------------------
# Heuristics for automatic domain grouping from tool names
# ---------------------------------------------------------------------------

DOMAIN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(sql|db|database|pg|postgres|mysql|mongo|redis|query)", re.I), "database"),
    (re.compile(r"^(github|git|gh|pr|repo|issue|commit|branch)", re.I),           "version_control"),
    (re.compile(r"^(fs|file|read|write|dir|path|disk|workspace)", re.I),           "filesystem"),
    (re.compile(r"^(web|search|browse|scrape|url|http|fetch)", re.I),              "web"),
    (re.compile(r"^(slack|discord|email|mail|notify|alert|message)", re.I),        "messaging"),
    (re.compile(r"^(k8s|kubectl|helm|deploy|docker|pod|service)", re.I),           "devops"),
    (re.compile(r"^(jira|linear|asana|notion|ticket|task|project)", re.I),         "project_mgmt"),
    (re.compile(r"^(stripe|payment|billing|invoice|charge|refund)", re.I),         "billing"),
]

DEFAULT_DOMAIN_CRITERIA: dict[str, str] = {
    "database":        "SQL, Postgres, MySQL, MongoDB, querying, tables, revenue, users",
    "version_control": "Git, GitHub, pull requests, code review, CI status, diffs",
    "filesystem":      "Reading files, searching files, local disk, code files",
    "web":             "Live internet, current news, URLs, scraping web pages",
    "messaging":       "Slack, Discord, email, notifications, alerts, chat channels",
    "devops":          "Kubernetes, Docker, deployments, pods, services, infra",
    "project_mgmt":    "Jira, Linear, tickets, tasks, sprints, project tracking",
    "billing":         "Stripe, payments, invoices, charges, subscriptions, refunds",
    "general":         "General-purpose tools that do not fit a specific category",
}


def infer_domain(tool_name: str) -> str:
    """Return a domain string for a tool name using prefix-matching heuristics."""
    for pattern, domain in DOMAIN_PATTERNS:
        if pattern.match(tool_name):
            return domain
    return "general"


def openai_tools_to_definitions(tools: list[dict[str, Any]]) -> list[ToolDefinition]:
    """
    Convert an OpenAI tools array into ToolDefinition objects.

    Automatically infers domain from tool name for two-pass Jev routing.
    """
    definitions: list[ToolDefinition] = []
    for item in tools:
        fn = item.get("function", item)  # handle {type, function} and bare dicts
        name = fn.get("name", "unknown")
        definitions.append(
            ToolDefinition(
                name=name,
                description=fn.get("description", ""),
                parameters=fn.get("parameters", {}),
                domain=infer_domain(name),
            )
        )
    return definitions


def extract_prompt(messages: list[dict[str, Any]]) -> str:
    """
    Extract the most relevant prompt string for Jev from the OpenAI messages array.

    Prefers the last user message; falls back to the last message of any role.
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal content — concatenate text parts only
                return " ".join(
                    p.get("text", "") for p in content if p.get("type") == "text"
                )
            return str(content)
    last = messages[-1] if messages else {}
    return str(last.get("content", ""))
