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
    (re.compile(r"^(sec|security|vuln|cve|osv|audit|scan|threat|ip_lookup)", re.I), "security"),
    (re.compile(r"^(net|network|ssl|tls|dns|ping|port)", re.I),                   "network"),
    (re.compile(r"^(sys|metric|metrics|monitor|system|perf|cpu|mem|health)", re.I), "monitoring"),
    (re.compile(r"^(web|search|browse|scrape|url|http|fetch)", re.I),              "web"),
    (re.compile(r"^(slack|discord|email|mail|notify|alert|message)", re.I),        "messaging"),
    (re.compile(r"^(k8s|kubectl|helm|deploy|docker|pod|service)", re.I),           "devops"),
    (re.compile(r"^(jira|linear|asana|notion|ticket|task|project)", re.I),         "project_mgmt"),
    (re.compile(r"^(stripe|payment|billing|invoice|charge|refund)", re.I),         "billing"),
]

DEFAULT_DOMAIN_CRITERIA: dict[str, str] = {
    "database":        "SQL, Postgres, SQLite, MySQL, querying, tables, revenue, users, database schema",
    "version_control": "Git, GitHub, pull requests, code review, CI status, diffs, git commits",
    "filesystem":      "Reading files, writing files, searching files, local disk, directory listing",
    "security":        "Security vulnerabilities, CVE scan, Google OSV database, IP geolocation, threat forensics",
    "network":         "SSL certificate check, TLS expiry, DNS resolution, HTTP latency ping",
    "monitoring":      "Host CPU usage, RAM memory, disk space, processes, service health, Prometheus metrics, alerts",
    "web":             "Live internet search, current sports fixtures, match schedules, upcoming events, real-time dates, news, looking up unknown acronyms, terms, products, technologies, or documentation",
    "messaging":       "Slack, Discord, email, notifications, alerts, chat channels, incident messages",
    "devops":          "Docker containers, docker logs, docker inspect, Kubernetes, deployments, pods, services",
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

    Automatically infers domain from tool name or explicit 'domain' key.
    """
    definitions: list[ToolDefinition] = []
    for item in tools:
        fn = item.get("function", item)  # handle {type, function} and bare dicts
        name = fn.get("name", "unknown")
        explicit_domain = fn.get("domain") or item.get("domain")
        definitions.append(
            ToolDefinition(
                name=name,
                description=fn.get("description", ""),
                parameters=fn.get("parameters", {}),
                domain=explicit_domain or infer_domain(name),
            )
        )
    return definitions


def _parse_content_text(content: Any) -> str:
    """Safely extract plain text from string, multimodal list, or None content."""
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        ).strip()
    return str(content).strip()


def extract_prompt(messages: list[dict[str, Any]]) -> str:
    """
    Extract the most relevant prompt string for Jev from the OpenAI messages array.

    Prefers the last user message; falls back to the last message of any role.
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            text = _parse_content_text(msg.get("content"))
            if text:
                return text
    if not messages:
        return ""
    return _parse_content_text(messages[-1].get("content"))
