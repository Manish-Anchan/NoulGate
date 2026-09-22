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

    # ── Tier 2: Auto-detect from Key Prefix or Model Name ────────────────────
    # Groq
    if token.startswith("gsk_") or any(
        kw in model_lower for kw in ("qwen", "llama-3", "llama3", "mixtral", "gemma-2", "whisper")
    ):
        return PROVIDER_PRESETS["groq"]

    # OpenRouter
    if token.startswith("sk-or-") or "/" in model_lower:
        return PROVIDER_PRESETS["openrouter"]

    # DeepSeek
    if token.startswith("dsk-") or "deepseek" in model_lower:
        return PROVIDER_PRESETS["deepseek"]

    # Together AI
    if token.startswith("tog_"):
        return PROVIDER_PRESETS["together"]

    # Mistral AI
    if "mistral" in model_lower and not any(m in model_lower for m in ("gpt", "claude")):
        return PROVIDER_PRESETS["mistral"]

    # ── Tier 3: Fallback ─────────────────────────────────────────────────────
    return default_fallback.rstrip("/")
