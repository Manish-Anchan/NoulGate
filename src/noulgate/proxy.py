"""
NoulGate Proxy Server
=====================
An OpenAI-compatible reverse proxy that sits between any agent/client and
the upstream LLM.  On every request it:

1. Extracts the user's last message + the ``tools`` array.
2. Runs NoulGateEngine.prune() to decide which tools are actually needed.
3. Forwards the slimmed request to the upstream LLM.
4. Streams the response back to the caller unchanged.

Drop-in usage
-------------
Any OpenAI SDK client or agent just needs one config change::

    client = openai.OpenAI(
        base_url="http://localhost:8080/v1",   # ← point here instead
        api_key="<your-openai-key>",
    )

Environment variables
---------------------
TYPESAFE_API_KEY    Required. TypeSafe AI key for Jev.
UPSTREAM_BASE_URL   Upstream LLM base URL.
                    Default: https://api.openai.com/v1
TOOL_THRESHOLD      Noul probability threshold (float, default 0.40).
"""

from __future__ import annotations

import os
import json
import logging
import re
from typing import Any, AsyncGenerator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from typesafe_sdk import TypeSafeClient

from noulgate.engine import NoulGateEngine, ToolDefinition

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("noulgate.proxy")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

UPSTREAM_BASE_URL: str = os.getenv("UPSTREAM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
TOOL_THRESHOLD: float = float(os.getenv("TOOL_THRESHOLD", "0.40"))

# ---------------------------------------------------------------------------
# Domain inference helpers
# ---------------------------------------------------------------------------

# Simple prefix → domain heuristic for auto-grouping ad-hoc tool lists.
# Order matters — first match wins.
_DOMAIN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(sql|db|database|pg|postgres|mysql|mongo|redis|query)", re.I), "database"),
    (re.compile(r"^(github|git|gh|pr|repo|issue|commit|branch)", re.I),          "version_control"),
    (re.compile(r"^(fs|file|read|write|dir|path|disk|workspace)", re.I),          "filesystem"),
    (re.compile(r"^(web|search|browse|scrape|url|http|fetch)", re.I),             "web"),
    (re.compile(r"^(slack|discord|email|mail|notify|alert|message)", re.I),       "messaging"),
    (re.compile(r"^(k8s|kubectl|helm|deploy|docker|pod|service)", re.I),          "devops"),
    (re.compile(r"^(jira|linear|asana|notion|ticket|task|project)", re.I),        "project_mgmt"),
    (re.compile(r"^(stripe|payment|billing|invoice|charge|refund)", re.I),        "billing"),
]

_DOMAIN_CRITERIA: dict[str, str] = {
    "database":     "SQL, Postgres, MySQL, MongoDB, querying, tables, revenue, users",
    "version_control": "Git, GitHub, pull requests, code review, CI status, diffs",
    "filesystem":   "Reading files, searching files, local disk, code files",
    "web":          "Live internet, current news, URLs, scraping web pages",
    "messaging":    "Slack, Discord, email, notifications, alerts, chat channels",
    "devops":       "Kubernetes, Docker, deployments, pods, services, infra",
    "project_mgmt": "Jira, Linear, tickets, tasks, sprints, project tracking",
    "billing":      "Stripe, payments, invoices, charges, subscriptions, refunds",
    "general":      "General-purpose tools that do not fit a specific category",
}


def _infer_domain(tool_name: str) -> str:
    """Return a domain string for a tool name using prefix-matching heuristics."""
    for pattern, domain in _DOMAIN_PATTERNS:
        if pattern.match(tool_name):
            return domain
    return "general"


def _openai_tools_to_definitions(tools: list[dict[str, Any]]) -> list[ToolDefinition]:
    """
    Convert an OpenAI ``tools`` array into :class:`ToolDefinition` objects.

    Automatically infers the ``domain`` from each tool's name so that
    NoulGateEngine can group them for two-pass Jev routing.
    """
    definitions: list[ToolDefinition] = []
    for item in tools:
        fn = item.get("function", item)  # handle both {type,function} and bare dicts
        name = fn.get("name", "unknown")
        definitions.append(
            ToolDefinition(
                name=name,
                description=fn.get("description", ""),
                parameters=fn.get("parameters", {}),
                domain=_infer_domain(name),
            )
        )
    return definitions


def _extract_prompt(messages: list[dict[str, Any]]) -> str:
    """
    Return the best prompt string for Jev from the messages array.

    Prefers the last user message; falls back to the last message of any role.
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal content — concatenate text parts
                return " ".join(
                    p.get("text", "") for p in content if p.get("type") == "text"
                )
            return str(content)
    # Fallback
    last = messages[-1] if messages else {}
    return str(last.get("content", ""))


# ---------------------------------------------------------------------------
# Engine (singleton, lazily initialised)
# ---------------------------------------------------------------------------

_engine: NoulGateEngine | None = None


def _get_engine() -> NoulGateEngine:
    global _engine
    if _engine is None:
        client = TypeSafeClient()  # reads TYPESAFE_API_KEY from env
        _engine = NoulGateEngine(client=client, tool_threshold=TOOL_THRESHOLD)
        # Pre-load domain criteria so the engine knows the rubrics
        _engine._domain_criteria.update(_DOMAIN_CRITERIA)
        log.info("NoulGateEngine initialised (threshold=%.2f)", TOOL_THRESHOLD)
    return _engine


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NoulGate",
    description="High-speed System 1 MCP tool gateway powered by TypeSafe AI's Jev.",
    version="0.1.0",
    docs_url="/docs",
)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# /v1/prune  (debug / inspect endpoint)
# ---------------------------------------------------------------------------


@app.post("/v1/prune", tags=["debug"])
async def prune_only(request: Request) -> JSONResponse:
    """
    Dry-run pruning endpoint.

    Send the same payload you would send to ``/v1/chat/completions`` and get
    back the pruning decision *without* forwarding anything to the upstream LLM.
    Useful for testing and visualising token savings.
    """
    body: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    raw_tools: list[dict[str, Any]] = body.get("tools", [])

    if not raw_tools:
        return JSONResponse({"needs_tool": False, "reason": "no tools in request"})

    prompt = _extract_prompt(messages)
    tool_defs = _openai_tools_to_definitions(raw_tools)
    result = _get_engine().prune(prompt, tool_defs)

    return JSONResponse({
        "needs_tool": result.needs_tool,
        "tool_probability": result.tool_probability,
        "selected_domain": result.selected_domain,
        "selected_tools": [t.name for t in result.selected_tools],
        "total_tools_input": result.total_tools_input,
        "total_tokens_input": result.total_tokens_input,
        "pruned_tokens_output": result.pruned_tokens_output,
        "token_savings": result.token_savings,
        "token_savings_pct": round(result.token_savings_pct, 1),
        "latency_ms": round(result.latency_ms, 1),
        "summary": result.summary(),
    })


# ---------------------------------------------------------------------------
# /v1/chat/completions  (main proxy)
# ---------------------------------------------------------------------------


async def _stream_upstream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> AsyncGenerator[bytes, None]:
    """Async generator that streams SSE bytes from the upstream LLM."""
    async with client.stream("POST", url, json=payload, headers=headers) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes():
            yield chunk


@app.post("/v1/chat/completions", tags=["proxy"])
async def chat_completions(request: Request) -> Response:
    """
    OpenAI-compatible chat completions proxy with Jev-powered tool pruning.

    The caller's ``Authorization`` header is forwarded to the upstream LLM
    (BYOK — Bring Your Own Key).  Only ``x-typesafe-api-key`` is consumed
    locally by NoulGate.
    """
    body: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    raw_tools: list[dict[str, Any]] = body.get("tools", [])
    stream: bool = body.get("stream", False)

    # ── Pruning ──────────────────────────────────────────────────────────────
    if raw_tools:
        prompt = _extract_prompt(messages)
        tool_defs = _openai_tools_to_definitions(raw_tools)
        result = _get_engine().prune(prompt, tool_defs)

        log.info(result.summary())

        if result.needs_tool:
            # Replace the full tool list with the pruned subset
            pruned_names = {t.name for t in result.selected_tools}
            body["tools"] = [
                t for t in raw_tools
                if t.get("function", t).get("name") in pruned_names
            ]
            # Preserve tool_choice if set, otherwise auto
            if "tool_choice" not in body:
                body["tool_choice"] = "auto"
        else:
            # No tool needed — strip all tool schemas to save tokens
            body.pop("tools", None)
            body.pop("tool_choice", None)
    else:
        log.info("Request has no tools — forwarding as-is.")

    # ── Forward to upstream ───────────────────────────────────────────────────
    upstream_url = f"{UPSTREAM_BASE_URL}/chat/completions"

    # Forward auth header (BYOK); strip NoulGate-specific headers
    forward_headers: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() in ("authorization", "content-type", "openai-organization"):
            forward_headers[key] = value

    async with httpx.AsyncClient(timeout=120.0) as client:
        if stream:
            return StreamingResponse(
                _stream_upstream(client, upstream_url, forward_headers, body),
                media_type="text/event-stream",
                headers={"X-NoulGate-Version": "0.1.0"},
            )
        else:
            resp = await client.post(upstream_url, json=body, headers=forward_headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return JSONResponse(
                content=resp.json(),
                headers={"X-NoulGate-Version": "0.1.0"},
            )
