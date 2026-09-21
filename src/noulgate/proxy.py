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
TYPESAFE_API_KEY    Required. TypeSafe AI key for Jev (server-side free-tier key).
UPSTREAM_BASE_URL   Upstream LLM base URL. Default: https://api.openai.com/v1
TOOL_THRESHOLD      Noul probability threshold (float, default 0.40).

Rate limiting (Hybrid BYOK)
---------------------------
Free tier  : 50 requests/day per IP — uses server's Jev key automatically.
Unlimited  : Pass your own TypeSafe key via header to skip the limit entirely:
               x-typesafe-api-key: apikey_...
Response headers returned on every request:
  X-RateLimit-Limit     always 50
  X-RateLimit-Remaining remaining calls today (or "unlimited" if BYOK)
  X-RateLimit-Reset     YYYY-MM-DD date when the counter resets (midnight UTC)
"""

from __future__ import annotations

import os
import logging
import re
import threading
from collections import defaultdict
from datetime import date, timezone, datetime
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
TOOL_THRESHOLD: float  = float(os.getenv("TOOL_THRESHOLD", "0.40"))

FREE_TIER_DAILY_LIMIT: int = 50  # requests per IP per day on the server's Jev key

# ---------------------------------------------------------------------------
# Rate limiter  (in-memory, resets daily at midnight UTC)
# ---------------------------------------------------------------------------

@staticmethod
def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# Structure: { ip: {"date": "YYYY-MM-DD", "count": int} }
_rate_store: dict[str, dict[str, Any]] = defaultdict(lambda: {"date": "", "count": 0})
_rate_lock  = threading.Lock()


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """
    Check and increment the daily request counter for *ip*.

    Returns:
        (is_allowed, remaining) — remaining is the quota left after this request.
    """
    today = _today_utc()
    with _rate_lock:
        rec = _rate_store[ip]
        if rec["date"] != today:          # new day — reset counter
            rec["date"]  = today
            rec["count"] = 0
        if rec["count"] >= FREE_TIER_DAILY_LIMIT:
            return False, 0
        rec["count"] += 1
        return True, FREE_TIER_DAILY_LIMIT - rec["count"]


def _rate_limit_headers(remaining: int | str) -> dict[str, str]:
    """Build the standard rate-limit response headers."""
    return {
        "X-RateLimit-Limit":     str(FREE_TIER_DAILY_LIMIT),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset":     _today_utc(),   # resets next UTC midnight
        "X-NoulGate-Version":    "0.1.0",
    }

# ---------------------------------------------------------------------------
# Domain inference helpers
# ---------------------------------------------------------------------------

# Simple prefix → domain heuristic for auto-grouping ad-hoc tool lists.
# Order matters — first match wins.
_DOMAIN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(sql|db|database|pg|postgres|mysql|mongo|redis|query)", re.I), "database"),
    (re.compile(r"^(github|git|gh|pr|repo|issue|commit|branch)", re.I),           "version_control"),
    (re.compile(r"^(fs|file|read|write|dir|path|disk|workspace)", re.I),           "filesystem"),
    (re.compile(r"^(web|search|browse|scrape|url|http|fetch)", re.I),              "web"),
    (re.compile(r"^(slack|discord|email|mail|notify|alert|message)", re.I),        "messaging"),
    (re.compile(r"^(k8s|kubectl|helm|deploy|docker|pod|service)", re.I),           "devops"),
    (re.compile(r"^(jira|linear|asana|notion|ticket|task|project)", re.I),         "project_mgmt"),
    (re.compile(r"^(stripe|payment|billing|invoice|charge|refund)", re.I),         "billing"),
]

_DOMAIN_CRITERIA: dict[str, str] = {
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
        fn   = item.get("function", item)   # handle both {type,function} and bare dicts
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
                # Multimodal content — concatenate text parts only
                return " ".join(
                    p.get("text", "") for p in content if p.get("type") == "text"
                )
            return str(content)
    last = messages[-1] if messages else {}
    return str(last.get("content", ""))


# ---------------------------------------------------------------------------
# Engine factory  (per-request when BYOK, singleton for server key)
# ---------------------------------------------------------------------------

_server_engine: NoulGateEngine | None = None


def _get_engine(byok_key: str | None = None) -> NoulGateEngine:
    """
    Return a NoulGateEngine instance.

    - If *byok_key* is provided, create a fresh engine with the caller's key.
      This bypasses the rate limiter entirely.
    - Otherwise return the shared singleton backed by the server's TYPESAFE_API_KEY.
    """
    if byok_key:
        engine = NoulGateEngine(
            client=TypeSafeClient(api_key=byok_key),
            tool_threshold=TOOL_THRESHOLD,
        )
        engine._domain_criteria.update(_DOMAIN_CRITERIA)
        return engine

    global _server_engine
    if _server_engine is None:
        _server_engine = NoulGateEngine(
            client=TypeSafeClient(),   # reads TYPESAFE_API_KEY from env
            tool_threshold=TOOL_THRESHOLD,
        )
        _server_engine._domain_criteria.update(_DOMAIN_CRITERIA)
        log.info("NoulGateEngine initialised (threshold=%.2f)", TOOL_THRESHOLD)
    return _server_engine


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
    """Simple liveness probe — used by Koyeb / Fly.io / Docker health checks."""
    return {"status": "ok", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# /v1/prune  (debug / inspect — also rate-limited)
# ---------------------------------------------------------------------------

@app.post("/v1/prune", tags=["debug"])
async def prune_only(request: Request) -> JSONResponse:
    """
    Dry-run pruning endpoint.

    Send the same payload you would to ``/v1/chat/completions`` and receive
    the pruning decision *without* forwarding to the upstream LLM.
    Great for testing and measuring token savings.
    """
    body: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    raw_tools: list[dict[str, Any]] = body.get("tools", [])

    if not raw_tools:
        return JSONResponse({"needs_tool": False, "reason": "no tools in request"})

    # ── BYOK or rate-limited? ────────────────────────────────────────────────
    byok_key: str | None = request.headers.get("x-typesafe-api-key")
    rl_headers: dict[str, str]

    if byok_key:
        engine    = _get_engine(byok_key)
        rl_headers = _rate_limit_headers("unlimited")
    else:
        client_ip = request.client.host if request.client else "unknown"
        allowed, remaining = _check_rate_limit(client_ip)
        rl_headers = _rate_limit_headers(remaining)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": (
                        f"Free tier limit of {FREE_TIER_DAILY_LIMIT} requests/day reached. "
                        "Pass your own TypeSafe key via the x-typesafe-api-key header to continue."
                    ),
                },
                headers=rl_headers,
            )
        engine = _get_engine()

    prompt    = _extract_prompt(messages)
    tool_defs = _openai_tools_to_definitions(raw_tools)
    result    = engine.prune(prompt, tool_defs)

    return JSONResponse(
        content={
            "needs_tool":          result.needs_tool,
            "tool_probability":    result.tool_probability,
            "selected_domain":     result.selected_domain,
            "selected_tools":      [t.name for t in result.selected_tools],
            "total_tools_input":   result.total_tools_input,
            "total_tokens_input":  result.total_tokens_input,
            "pruned_tokens_output":result.pruned_tokens_output,
            "token_savings":       result.token_savings,
            "token_savings_pct":   round(result.token_savings_pct, 1),
            "latency_ms":          round(result.latency_ms, 1),
            "summary":             result.summary(),
        },
        headers=rl_headers,
    )


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

    - The caller's ``Authorization`` header is forwarded to the upstream LLM (BYOK).
    - ``x-typesafe-api-key`` is consumed locally by NoulGate and never forwarded.
    - Free tier: 50 requests/day per IP using the server's Jev key.
    - Unlimited: pass ``x-typesafe-api-key`` header with your own TypeSafe key.
    """
    body: dict[str, Any]          = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    raw_tools: list[dict[str, Any]] = body.get("tools", [])
    stream: bool                   = body.get("stream", False)

    # ── BYOK or rate-limited? ────────────────────────────────────────────────
    byok_key: str | None = request.headers.get("x-typesafe-api-key")
    rl_headers: dict[str, str]

    if byok_key:
        engine    = _get_engine(byok_key)
        rl_headers = _rate_limit_headers("unlimited")
        log.info("BYOK key detected — rate limit bypassed.")
    else:
        client_ip = request.client.host if request.client else "unknown"
        allowed, remaining = _check_rate_limit(client_ip)
        rl_headers = _rate_limit_headers(remaining)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Free tier limit of {FREE_TIER_DAILY_LIMIT} requests/day reached. "
                    "Pass your own TypeSafe key via the x-typesafe-api-key header to continue."
                ),
                headers=rl_headers,
            )
        engine = _get_engine()

    # ── Pruning ──────────────────────────────────────────────────────────────
    if raw_tools:
        prompt    = _extract_prompt(messages)
        tool_defs = _openai_tools_to_definitions(raw_tools)
        result    = engine.prune(prompt, tool_defs)
        log.info(result.summary())

        if result.needs_tool:
            pruned_names = {t.name for t in result.selected_tools}
            body["tools"] = [
                t for t in raw_tools
                if t.get("function", t).get("name") in pruned_names
            ]
            if "tool_choice" not in body:
                body["tool_choice"] = "auto"
        else:
            body.pop("tools", None)
            body.pop("tool_choice", None)
    else:
        log.info("Request has no tools — forwarding as-is.")

    # ── Forward to upstream ───────────────────────────────────────────────────
    upstream_url = f"{UPSTREAM_BASE_URL}/chat/completions"

    forward_headers: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() in ("authorization", "content-type", "openai-organization"):
            forward_headers[key] = value

    async with httpx.AsyncClient(timeout=120.0) as http:
        if stream:
            return StreamingResponse(
                _stream_upstream(http, upstream_url, forward_headers, body),
                media_type="text/event-stream",
                headers=rl_headers,
            )
        else:
            resp = await http.post(upstream_url, json=body, headers=forward_headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return JSONResponse(content=resp.json(), headers=rl_headers)
