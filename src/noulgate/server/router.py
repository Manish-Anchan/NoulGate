"""
noulgate.server.router
======================
3-Tier dynamic multi-provider upstream URL resolver.
"""

from __future__ import annotations

import os

UPSTREAM_BASE_URL: str = os.getenv("UPSTREAM_BASE_URL", "https://api.openai.com/v1").rstrip("/")

PROVIDER_PRESETS: dict[str, str] = {
    "groq":       "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek":   "https://api.deepseek.com/v1",
    "together":   "https://api.together.xyz/v1",
    "mistral":    "https://api.mistral.ai/v1",
    "openai":     "https://api.openai.com/v1",
}


def resolve_upstream_base_url(
    custom_header_url: str | None = None,
    auth_header: str | None = None,
    model_name: str = "",
    default_fallback: str = UPSTREAM_BASE_URL,
) -> str:
    """
    3-Tier resolution of upstream LLM base URL:
    - Tier 1: Explicit 'x-upstream-base-url' client header override.
    - Tier 2: Auto-detect from Auth key prefix or Model name.
    - Tier 3: Fall back to UPSTREAM_BASE_URL (default: https://api.openai.com/v1).
    """
    # ── Tier 1: Client explicit header override ───────────────────────────────
    if custom_header_url and custom_header_url.strip():
        return custom_header_url.strip().rstrip("/")

    token = ""
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()

    model_lower = (model_name or "").lower()

    # ── Tier 2A: Detect provider strictly by unambiguous API Key Prefix ──────
    if token.startswith("gsk_"):
        return PROVIDER_PRESETS["groq"]
    if token.startswith("sk-or-"):
        return PROVIDER_PRESETS["openrouter"]
    if token.startswith(("tog_", "together_")):
        return PROVIDER_PRESETS["together"]
    if token.startswith("dsk-"):
        return PROVIDER_PRESETS["deepseek"]

    # ── Tier 2B: Detect provider from Model Name (when key prefix is generic) ─
    if "/" in model_lower:
        # Universal multi-provider format (e.g. meta-llama/..., qwen/... on OpenRouter)
        return PROVIDER_PRESETS["openrouter"]

    if "deepseek" in model_lower:
        return PROVIDER_PRESETS["deepseek"]

    if "mistral" in model_lower and not any(m in model_lower for m in ("gpt", "claude")):
        return PROVIDER_PRESETS["mistral"]

    if any(kw in model_lower for kw in ("llama-3", "llama3", "mixtral", "gemma-2", "whisper", "qwen")):
        return PROVIDER_PRESETS["groq"]

    # ── Tier 3: Fallback ─────────────────────────────────────────────────────
    return default_fallback.rstrip("/")
