# NoulGate

> **A high-speed System 1 gateway that prunes MCP tool bloat before it reaches your LLM.**

When you connect 5+ MCP servers to an AI agent, you can easily end up with 30–60 tool schemas injected into every single request — even when the user just says *"Thanks!"*. This costs thousands of tokens, slows down responses, and causes models to confuse similar tools and hallucinate tool calls.

NoulGate fixes this. It sits between your agent and the LLM, evaluating each prompt with [TypeSafe AI's Jev](https://typesafe.ai) model in ~100ms and pruning the tool list down to the 1–2 tools actually needed — or stripping all tools entirely for conversational turns.

---

## How It Works

```
Your Agent / Cursor / Claude Desktop
          │
          │  POST /v1/chat/completions
          │  { messages: [...], tools: [30 tools, ~8000 tokens] }
          ▼
┌─────────────────────────────────────────┐
│            NoulGate Gateway             │
│                                         │
│  1. Extract user's last message         │
│  2. Jev evaluates in ~100ms:            │
│     • Noul  — tool needed? (0–1)        │
│     • Choice — which domain?            │
│  3. Prune 30 tools → 1 tool             │
│  4. Forward lean request upstream       │
└─────────────────────────────────────────┘
          │
          │  POST https://api.openai.com/v1/chat/completions
          │  { messages: [...], tools: [1 tool, ~200 tokens] }
          ▼
     OpenAI / Anthropic / any LLM
```

**Result:** Up to 95% token reduction on tool schemas, faster responses, and zero tool-confusion hallucinations.

---

## Quickstart

### Option 1 — Local (Python)

```bash
# 1. Clone and install
git clone https://github.com/manishanchan/noulgate
cd noulgate
uv sync

# 2. Set your TypeSafe AI key (get one at typesafe.ai)
echo "TYPESAFE_API_KEY=apikey_..." > .env

# 3. Start the gateway
uv run noulgate --port 8080
```

### Option 2 — Docker

```bash
docker build -t noulgate .
docker run -p 8080:8080 -e TYPESAFE_API_KEY=apikey_... noulgate
```

### Option 3 — Hosted (Zero Setup)

Use the public hosted instance — no installation required.
The server's Jev key is included (free tier: 50 requests/day per IP).

```
https://noulgate.koyeb.app/v1
```

---

## Integration

NoulGate is a **drop-in replacement** for any OpenAI-compatible base URL. Change one line:

### Python (OpenAI SDK)

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8080/v1",  # ← only change
    api_key="sk-proj-your-openai-key",
)

# Everything else stays the same — tools are pruned automatically
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What was revenue last week?"}],
    tools=[...30 MCP tools...],
)
```

### Cursor

Settings → Models → Custom API → Base URL: `http://localhost:8080/v1`

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "noulgate": {
      "url": "http://localhost:8080/v1/chat/completions"
    }
  }
}
```

---

## API Endpoints

| Method | Path | Description |
|:---|:---|:---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/docs` | Interactive Swagger UI |
| `POST` | `/v1/chat/completions` | Main proxy — prunes tools, forwards to LLM |
| `POST` | `/v1/prune` | Debug — returns pruning decision without calling LLM |

### `/v1/prune` — Debug Endpoint

Test what NoulGate would do to your tools without spending any LLM tokens:

```bash
curl -X POST http://localhost:8080/v1/prune \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Check if PR 42 is merged"}],
    "tools": [
      {"type": "function", "function": {"name": "github_get_pr", "description": "Fetch a PR", "parameters": {}}},
      {"type": "function", "function": {"name": "sql_query_runner", "description": "Run SQL", "parameters": {}}},
      {"type": "function", "function": {"name": "web_search", "description": "Search web", "parameters": {}}}
    ]
  }'
```

Response:

```json
{
  "needs_tool": true,
  "selected_tools": ["github_get_pr"],
  "token_savings": 312,
  "token_savings_pct": 88.0,
  "latency_ms": 143.2,
  "summary": "🎯 Tool needed (p=0.94) → domain='version_control' → tools=['github_get_pr'] | saved 312 tokens (88%) in 143ms"
}
```

---

## Rate Limits

Every response includes standard rate-limit headers:

```
X-RateLimit-Limit:     50
X-RateLimit-Remaining: 34
X-RateLimit-Reset:     2026-09-22
```

| Tier | Limit | How |
|:---|:---|:---|
| **Free** | 50 requests / day / IP | No setup needed — uses server's Jev key |
| **Unlimited** | No limit | Pass your own key: `x-typesafe-api-key: apikey_...` |

Get your own TypeSafe API key at [typesafe.ai](https://typesafe.ai).

---

## Configuration

| Environment Variable | Default | Description |
|:---|:---|:---|
| `TYPESAFE_API_KEY` | — | **Required.** Your TypeSafe AI (Jev) API key |
| `UPSTREAM_BASE_URL` | `https://api.openai.com/v1` | Upstream LLM endpoint |
| `TOOL_THRESHOLD` | `0.40` | Minimum Noul probability to consider a tool needed |

---

## Deploy for Free

### Koyeb (Recommended)

1. Fork this repository.
2. Go to [app.koyeb.com](https://app.koyeb.com) → New Service → GitHub.
3. Set `TYPESAFE_API_KEY` as a secret environment variable.
4. Deploy. Done — you get a free HTTPS URL.

### Hugging Face Spaces (Docker)

1. Create a new Space → Docker SDK.
2. Push the repository contents.
3. Add `TYPESAFE_API_KEY` in Space Secrets.

### Fly.io

```bash
fly launch
fly secrets set TYPESAFE_API_KEY=apikey_...
fly deploy
```

---

## Self-Hosting (Using Your Own Key as a User)

If you self-host NoulGate, set your own `TYPESAFE_API_KEY` in the environment.
The rate limiter only applies when using the **server operator's** key.
Your own instance has no built-in limit.

---

## 3-Tier Dynamic Multi-Provider Routing

NoulGate is not locked to one LLM provider. It dynamically routes each request:

1. **Tier 1 (Header Override):** Pass `x-upstream-base-url: https://...` to route anywhere (e.g. local Ollama, vLLM, Azure).
2. **Tier 2 (Auto-Detection):** Detects provider automatically by key prefix or model name:
   - `gsk_...` or `qwen`, `llama` → `https://api.groq.com/openai/v1`
   - `sk-or-...` → `https://openrouter.ai/api/v1`
   - `deepseek...` → `https://api.deepseek.com/v1`
   - `tog_...` → `https://api.together.xyz/v1`
3. **Tier 3 (Default Fallback):** Defaults to `https://api.openai.com/v1`.

---

## Benchmarks (Live Test: 36 MCP Tools across 8 Domains)

Tested live with Qwen-32B via Groq with 36 tools registered (GitHub, Postgres, K8s, Slack, Jira, Grafana, Filesystem, Web Search):

| Query Type | Tools Sent | Tools Forwarded to LLM | Schema Tokens Saved | Routing Accuracy |
|:---|:---:|:---:|:---:|:---:|
| **Casual conversation** (e.g. "Explain blue/green vs canary") | 36 | **0** | **6,480 tokens (100%)** | ✅ 100% |
| **GitHub actions** (e.g. "Is PR #142 ready to merge?") | 36 | **1** (`github_get_pr`) | **6,300 tokens (97.2%)** | ✅ 100% |
| **Database diagnostics** (e.g. "Top slow queries in Postgres") | 36 | **1** (`db_get_slow_queries`) | **6,300 tokens (98.8%)** | ✅ 100% |
| **Kubernetes infra** (e.g. "Are production pods healthy?") | 36 | **1** (`k8s_get_pods`) | **6,300 tokens (97.1%)** | ✅ 100% |
| **Slack alerts** (e.g. "Post deploy message to #deployments") | 36 | **1** (`slack_post_message`) | **6,300 tokens (97.2%)** | ✅ 100% |
| **Monitoring SLOs** (e.g. "Health score for api service") | 36 | **1** (`metrics_get_service_health`) | **6,300 tokens (97.2%)** | ✅ 100% |
| **Jira ticket search** (e.g. "Search auth issues in Jira") | 36 | **1** (`jira_search_tickets`) | **6,300 tokens (97.2%)** | ✅ 100% |
| **Overall 10-Query Suite** | **36** | **0 to 1** | **~63,000+ total tokens saved** | **10/10 (100%)** |

---

## Project Structure

```
NoulGate/
├── src/noulgate/
│   ├── __init__.py          Public package exports
│   ├── cli.py               CLI entrypoint (noulgate command)
│   ├── core/                Core pruning engine & data models
│   │   ├── models.py        ToolDefinition, PruneResult
│   │   ├── domains.py       Domain inference heuristics & OpenAI parsers
│   │   └── engine.py        NoulGateEngine (Jev System 1 model)
│   └── server/              Production FastAPI proxy gateway
│       ├── app.py           FastAPI app factory & CORS middleware
│       ├── rate_limit.py    Daily IP rate limiter & quota headers
│       ├── router.py        3-tier multi-provider URL resolver
│       └── routes.py        /health, /v1/prune, /v1/chat/completions
├── verify_engine.py         Live verification suite (8 prompts, 5 domains)
├── Dockerfile               Multi-stage production Docker build
├── pyproject.toml           uv project manifest
└── uv.lock                  Reproducible lockfile
```

---

## License

MIT © [Manish Anchan](https://github.com/manishanchan)
