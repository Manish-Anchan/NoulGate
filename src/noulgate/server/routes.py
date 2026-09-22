"""
noulgate.server.routes
======================
FastAPI routes for NoulGate proxy:
- GET  /health
- POST /v1/prune
- POST /v1/chat/completions
"""

from __future__ import annotations

import logging
import os
from typing import Any, AsyncGenerator

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from typesafe_sdk import TypeSafeClient

load_dotenv()

from noulgate.core.domains import (
    DEFAULT_DOMAIN_CRITERIA,
    extract_prompt,
    openai_tools_to_definitions,
)
from noulgate.core.engine import NoulGateEngine
from noulgate.server.rate_limit import (
    FREE_TIER_DAILY_LIMIT,
    check_rate_limit,
    rate_limit_headers,
)
from noulgate.server.router import UPSTREAM_BASE_URL, resolve_upstream_base_url

log = logging.getLogger("noulgate.server")
router = APIRouter()

TOOL_THRESHOLD: float = float(os.getenv("TOOL_THRESHOLD", "0.40"))

# ---------------------------------------------------------------------------
# Engine management
# ---------------------------------------------------------------------------

_server_engine: NoulGateEngine | None = None


def get_engine(byok_key: str | None = None) -> NoulGateEngine:
    """Return a NoulGateEngine instance (per-request for BYOK, singleton for server key)."""
    if byok_key:
        engine = NoulGateEngine(
            client=TypeSafeClient(api_key=byok_key),
            tool_threshold=TOOL_THRESHOLD,
        )
        engine._domain_criteria.update(DEFAULT_DOMAIN_CRITERIA)
        return engine

    global _server_engine
    if _server_engine is None:
        _server_engine = NoulGateEngine(
            client=TypeSafeClient(),
            tool_threshold=TOOL_THRESHOLD,
        )
        _server_engine._domain_criteria.update(DEFAULT_DOMAIN_CRITERIA)
        log.info("NoulGateEngine initialized (threshold=%.2f)", TOOL_THRESHOLD)
    return _server_engine


# ---------------------------------------------------------------------------
# Upstream Streaming Helper
# ---------------------------------------------------------------------------


async def stream_upstream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> AsyncGenerator[bytes, None]:
    """Stream SSE bytes directly from upstream LLM to client."""
    async with client.stream("POST", url, json=payload, headers=headers) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes():
            yield chunk


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe used by Docker, Kubernetes, and Cloud providers."""
    return {"status": "ok", "version": "0.1.0"}


@router.post("/v1/prune", tags=["debug"])
async def prune_only(request: Request) -> JSONResponse:
    """
    Debug endpoint: inspect the pruning decision and token metrics
    without forwarding anything to the upstream LLM.
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "message": "Please provide a valid JSON body.",
            },
        )

    messages: list[dict[str, Any]] = body.get("messages", [])
    raw_tools: list[dict[str, Any]] = body.get("tools", [])

    if not raw_tools:
        return JSONResponse({"needs_tool": False, "reason": "no tools in request"})

    # Rate limiting & BYOK check
    byok_key: str | None = request.headers.get("x-typesafe-api-key")
    if byok_key:
        engine = get_engine(byok_key)
        rl_headers = rate_limit_headers("unlimited")
    else:
        client_ip = request.client.host if request.client else "unknown"
        allowed, remaining = check_rate_limit(client_ip)
        rl_headers = rate_limit_headers(remaining)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": (
                        f"Free tier limit of {FREE_TIER_DAILY_LIMIT} requests/day reached. "
                        "Pass your own TypeSafe key via x-typesafe-api-key header to continue."
                    ),
                },
                headers=rl_headers,
            )
        engine = get_engine()

    prompt = extract_prompt(messages)
    tool_defs = openai_tools_to_definitions(raw_tools)
    result = engine.prune(prompt, tool_defs)

    return JSONResponse(
        content={
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
        },
        headers=rl_headers,
    )


@router.post("/v1/chat/completions", tags=["proxy"])
async def chat_completions(request: Request) -> Response:
    """
    OpenAI-compatible chat completions proxy with Jev System 1 tool pruning.
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "message": "Please provide a valid JSON body.",
            },
        )

    messages: list[dict[str, Any]] = body.get("messages", [])
    raw_tools: list[dict[str, Any]] = body.get("tools", [])
    stream: bool = body.get("stream", False)

    # Rate limiting & BYOK check
    byok_key: str | None = request.headers.get("x-typesafe-api-key")
    if byok_key:
        engine = get_engine(byok_key)
        rl_headers = rate_limit_headers("unlimited")
    else:
        client_ip = request.client.host if request.client else "unknown"
        allowed, remaining = check_rate_limit(client_ip)
        rl_headers = rate_limit_headers(remaining)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Free tier limit of {FREE_TIER_DAILY_LIMIT} requests/day reached. "
                    "Pass your own TypeSafe key via x-typesafe-api-key header to continue."
                ),
                headers=rl_headers,
            )
        engine = get_engine()

    # Pruning with Graceful Fallback
    if raw_tools:
        prompt = extract_prompt(messages)
        tool_defs = openai_tools_to_definitions(raw_tools)
        try:
            result = engine.prune(prompt, tool_defs)
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
        except Exception as exc:
            log.warning("Pruning error (falling back to all tools): %s", exc)
    else:
        log.info("Request has no tools — forwarding as-is.")

    # 3-Tier Multi-Provider Upstream Resolution
    custom_upstream = request.headers.get("x-upstream-base-url")
    auth_header = request.headers.get("authorization")
    model_name = body.get("model", "")

    resolved_base = resolve_upstream_base_url(
        custom_header_url=custom_upstream,
        auth_header=auth_header,
        model_name=model_name,
        default_fallback=UPSTREAM_BASE_URL,
    )
    upstream_url = f"{resolved_base}/chat/completions"
    log.info("Routing request to upstream: %s (model=%s)", upstream_url, model_name)

    forward_headers: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() in ("authorization", "content-type", "openai-organization"):
            forward_headers[key] = value

    async with httpx.AsyncClient(timeout=120.0) as http:
        if stream:
            return StreamingResponse(
                stream_upstream(http, upstream_url, forward_headers, body),
                media_type="text/event-stream",
                headers=rl_headers,
            )
        else:
            resp = await http.post(upstream_url, json=body, headers=forward_headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return JSONResponse(content=resp.json(), headers=rl_headers)
