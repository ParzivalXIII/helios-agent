# Quickstart: MCP Agent Service

**Feature**: `001-mcp-langgraph-agent`  
**Date**: 2026-04-06

---

## Prerequisites

- Python 3.12+
- `uv` package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- Docker + Docker Compose 3.8+
- Access to the `openrouter-llm` container image

---

## 1. Clone & Install

```bash
git clone <repo-url> helios-agent
cd helios-agent
uv sync
```

---

## 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
# LLM
LLM_BASE_URL=http://localhost:8001          # openrouter-llm container
LLM_MODEL=openai/gpt-4o-mini

# Session store
REDIS_URL=redis://localhost:6379

# Agent limits
MAX_TURNS=5
SESSION_TTL_SECONDS=3600
TOOL_TIMEOUT_MS=5000

# Logging
LOG_LEVEL=INFO

# MCP
MCP_CONFIG_PATH=config/mcp_servers.yaml
```

---

## 3. Configure MCP Servers

Edit `config/mcp_servers.yaml` to declare which MCP servers to connect at startup:

```yaml
mcp_servers:
  - name: filesystem
    type: stdio
    command: ["uvx", "mcp-server-filesystem", "--root", "/data"]

  - name: my_remote_tool
    type: sse
    url: http://my-mcp-server:8080/sse

  - name: custom_local
    type: fastmcp
    module: mcp_agent.mcp.server     # FastMCP server defined in this project
```

---

## 4. Start Infrastructure Services

```bash
docker compose up -d redis
```

> The `openrouter-llm` container must also be running. Refer to its own README for startup instructions.

---

## 5. Run the Agent Service

```bash
uv run uvicorn mcp_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

Expected startup output:

```
INFO  Starting MCP Agent
INFO  Connected to Redis url=redis://localhost:6379
INFO  Initializing MCP server name=filesystem type=stdio
INFO  Discovered 4 tools from filesystem
INFO  Tool registry built: 4 tools
INFO  LangGraph agent built
INFO  Startup complete
INFO  Application startup complete.
```

---

## 6. Send Your First Message

```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What files are in the /data directory?"}' | python3 -m json.tool
```

Expected response:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "The /data directory contains: file1.txt, report.csv, notes.md",
  "success": true,
  "turn_count": 1,
  "tool_calls": [
    {
      "tool_id": "filesystem.list_directory",
      "status": "success",
      "duration_ms": 85,
      "fallback_used": null
    }
  ],
  "duration_ms": 1240,
  "error": null,
  "metadata": {}
}
```

---

## 7. Continue a Multi-Turn Conversation

```bash
SESSION_ID="550e8400-e29b-41d4-a716-446655440000"

curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"What is in file1.txt?\", \"session_id\": \"$SESSION_ID\"}" \
  | python3 -m json.tool
```

---

## 8. Inspect Session State

```bash
curl -s http://localhost:8000/api/session/$SESSION_ID | python3 -m json.tool
```

---

## 9. Check Service Health

```bash
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

---

## 10. Run Tests

```bash
# All tests
uv run pytest

# Unit tests only
uv run pytest -m unit -v

# Integration tests only
uv run pytest -m integration -v

# With coverage
uv run pytest --cov=mcp_agent --cov-report=term-missing
```

---

## Full Docker Compose Stack

```bash
docker compose up --build
```

This starts: Redis + openrouter-llm + helios-agent together. The `POST /api/chat` endpoint will be available at `http://localhost:8000/api/chat`.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `provider_unavailable` on every request | `openrouter-llm` container not running | `docker compose up openrouter-llm` |
| `session_not_found` immediately | Redis not running | `docker compose up redis` |
| No tools discovered at startup | `mcp_servers.yaml` misconfigured or MCP server not reachable | Check `MCP_CONFIG_PATH` env var and server connectivity |
| `session_locked` on first request | Previous request did not release lock (crash) | Wait 30s for lock TTL to expire, then retry |
| Graph node error in logs | LLM returned an unparseable decision format | Check `LOG_LEVEL=DEBUG` output for `node_think` output |
