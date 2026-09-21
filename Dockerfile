# ── Stage 1: dependency resolver ──────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy lockfile and project manifest first (layer cache — deps rarely change)
COPY pyproject.toml uv.lock ./

# Install dependencies into a fixed location (no editable install yet)
RUN uv sync --frozen --no-install-project --no-dev

# Copy source and install the project itself
COPY src/ ./src/
RUN uv sync --frozen --no-dev


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Copy the fully-installed virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Copy source (needed at runtime for the installed package)
COPY --from=builder /app/src ./src

# Make the venv's binaries available on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1   \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Liveness probe — matches /health endpoint in proxy.py
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["noulgate", "--host", "0.0.0.0", "--port", "8080"]
