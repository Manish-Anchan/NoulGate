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

## Benchmarks

Tested with 10 MCP tools across 5 domains (database, github, filesystem, web, slack):

| Query type | Token savings | Jev latency |
|:---|:---|:---|
| Casual / conversational | 100% (all tools stripped) | 90–150ms |
| Single-domain tool query | 88–92% | 150–300ms |
| Multi-domain (2-pass) | 85–90% | 250–500ms |

---

## Project Structure

```
NoulGate/
├── src/noulgate/
│   ├── __init__.py     Public API exports
│   ├── engine.py       Core Jev decision engine (NoulGateEngine, ToolDefinition, PruneResult)
│   ├── proxy.py        OpenAI-compatible FastAPI proxy server
│   └── cli.py          Terminal entrypoint (noulgate command)
├── verify_engine.py    Live verification test (8 prompts, 5 domains)
├── Dockerfile          Multi-stage Docker build
├── pyproject.toml      uv project manifest
└── uv.lock             Reproducible dependency lockfile
```

---

## License

MIT © [Manish Anchan](https://github.com/manishanchan)
