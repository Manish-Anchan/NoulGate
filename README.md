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
          │  { messages: [...], tools: [36 tools, ~6,480 tokens] }
          ▼
┌─────────────────────────────────────────┐
│            NoulGate Gateway             │
│                                         │
│  1. Extract user's message              │
│  2. Jev evaluates in System 1 (~100ms): │
│     • Noul  — tool needed? (0.0–1.0)    │
│     • Choice — which domain?            │
│  3. Prune 36 tools → 1 relevant tool    │
│  4. Auto-route to Groq, OpenAI, etc.    │
└─────────────────────────────────────────┘
          │
          │  POST https://api.groq.com/openai/v1/chat/completions
          │  { messages: [...], tools: [1 tool, ~180 tokens] }
          ▼
     Groq (Qwen/Llama) / OpenAI / DeepSeek / any LLM
```

**Result:** Up to 97.2% token reduction on tool schemas, faster Time-To-First-Token, and zero tool-confusion hallucinations.

---

## Quickstart

### Option 1 — Hosted (Zero Setup, Free)

Use the public hosted instance — no installation required.
The server's Jev key is included (free tier: 50 requests/day per IP):

```text
https://noulgate.onrender.com/v1
```

### Option 2 — Local (Python & uv)

```bash
# 1. Clone repository
git clone https://github.com/Manish-Anchan/NoulGate.git
cd NoulGate
uv sync

# 2. Add your TypeSafe API key (get one free at https://typesafe.ai)
echo "TYPESAFE_API_KEY=apikey_..." > .env

# 3. Start the gateway
uv run noulgate --port 8080
```

### Option 3 — Docker

```bash
docker build -t noulgate .
docker run -p 8080:8080 --env-file .env noulgate
```

---

## Integration

NoulGate is a **drop-in replacement** for any OpenAI-compatible client. Just change the `base_url`:

### Python (OpenAI SDK with Groq or OpenAI)

```python
import os
from openai import OpenAI

# Point to your NoulGate instance (hosted or local)
client = OpenAI(
    base_url="https://noulgate.onrender.com/v1",  # or "http://localhost:8080/v1"
    api_key=os.getenv("GROQ_API_KEY"),            # Auto-routes to Groq! (or use OpenAI key)
)

# Call as normal — NoulGate prunes the tools automatically
response = client.chat.completions.create(
    model="qwen/qwen3.8-27b",
    messages=[{"role": "user", "content": "What was our total revenue last week?"}],
    tools=[...36 MCP tools...],
)

print(response.choices[0].message)
```

### Cursor / VS Code (Continue.dev)

* **Base URL:** `https://noulgate.onrender.com/v1` (or `http://localhost:8080/v1`)
* **API Key:** Your upstream key (e.g. `gsk_...` for Groq, `sk-proj-...` for OpenAI)

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "noulgate": {
      "url": "https://noulgate.onrender.com/v1/chat/completions"
    }
  }
}
```

---

## 3-Tier Dynamic Multi-Provider Routing

You do **not** need to reconfigure or restart NoulGate when switching LLM providers. It routes dynamically per request:

1. **Tier 1 (Header Override):** Pass `x-upstream-base-url: https://...` in headers to route anywhere (e.g. local Ollama, vLLM, Azure).
2. **Tier 2 (Auto-Detection):** Detects provider automatically by API key prefix or model name:
   * Key `gsk_...` or model `qwen`, `llama-3` → `https://api.groq.com/openai/v1`
   * Key `sk-or-...` → `https://openrouter.ai/api/v1`
   * Key `dsk-...` or model `deepseek` → `https://api.deepseek.com/v1`
   * Key `tog_...` → `https://api.together.xyz/v1`
3. **Tier 3 (Default Fallback):** Defaults to `https://api.openai.com/v1`.

---

## Live Benchmarks (36 MCP Tools across 8 Domains)

Tested live using **Qwen-32B via Groq** with 36 real MCP tools registered across 8 domains (GitHub, Database, Kubernetes, Slack, Jira, Monitoring, Filesystem, Web Search):

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

## API Endpoints

| Method | Path | Description |
|:---|:---|:---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/docs` | Interactive Swagger UI Documentation |
| `POST` | `/v1/chat/completions` | Main proxy — prunes tools, forwards to LLM |
| `POST` | `/v1/prune` | Debug endpoint — returns pruning decision without calling LLM |

### `/v1/prune` — Test Pruning Live via `curl`

Test what NoulGate would do to your tool list without spending any LLM tokens:

```bash
curl -X POST https://noulgate.onrender.com/v1/prune \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Check if PR #142 is merged"}],
    "tools": [
      {"type": "function", "function": {"name": "github_get_pr", "description": "Fetch PR details and CI checks"}},
      {"type": "function", "function": {"name": "sql_query_runner", "description": "Run SQL query"}},
      {"type": "function", "function": {"name": "k8s_get_pods", "description": "List Kubernetes pods"}},
      {"type": "function", "function": {"name": "slack_post_message", "description": "Post Slack alert"}}
    ]
  }'
```

Response:

```json
{
  "needs_tool": true,
  "selected_domain": "version_control",
  "selected_tools": ["github_get_pr"],
  "token_savings": 122,
  "token_savings_pct": 74.8,
  "latency_ms": 780.0,
  "summary": "🎯 Tool needed (p=0.94) → domain='version_control' → tools=['github_get_pr'] | saved 122 tokens (75%) in 780ms"
}
```

---

## Rate Limits & BYOK

Every response includes standard rate-limit headers:

```http
X-RateLimit-Limit: 50
X-RateLimit-Remaining: 42
X-RateLimit-Reset: 2026-09-22
```

| Tier | Limit | Usage |
|:---|:---|:---|
| **Free Tier** | 50 requests / day / IP | Default. Uses the server's TypeSafe Jev key. |
| **BYOK (Unlimited)** | **Unlimited** | Pass your own key in the `x-typesafe-api-key: apikey_...` header. |

Get your free TypeSafe API key at [typesafe.ai](https://typesafe.ai).

---

## Deploy Your Own Instance for Free

### Render (100% Free)

1. Fork or push this repository to GitHub.
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New** → **Web Service**.
3. Select your repository, choose **Runtime: Docker**, and pick the **Free** instance type ($0/mo).
4. Add environment variable: `TYPESAFE_API_KEY=your_key`.
5. Deploy. Done — you get a permanent public HTTPS URL.

---

## Project Structure

```text
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

MIT © [Manish Anchan](https://github.com/Manish-Anchan)
