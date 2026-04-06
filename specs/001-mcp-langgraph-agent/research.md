# Research: MCP-Integrated LangGraph Agent

**Feature**: `001-mcp-langgraph-agent`  
**Date**: 2026-04-06  
**Status**: Complete — all NEEDS CLARIFICATION resolved

---

## 1. LangGraph State Architecture

### Decision

Use Python dataclasses (not TypedDict) for `AgentState`, compiled with `StateGraph(AgentState)`.

### Rationale

LangGraph 1.x supports both TypedDict and dataclass-based state. Dataclasses provide:

- Default field factories (e.g., `field(default_factory=list)`) for mutable defaults
- Better IDE autocompletion and pyright coverage
- Direct attribute access (`state.messages`) vs dict-style access

The user-supplied `AgentState` in the technical requirements already uses `@dataclass`, confirming this choice.

### Alternatives Considered

- **TypedDict**: LangGraph's original state type — simpler but no validators, no field factories
- **Pydantic BaseModel**: Immutable by default; requires workarounds for in-place mutations in graph nodes

---

## 2. MCP Transport & Connection Strategy

### Decision

Support three transport types in the aggregator: `stdio` (subprocess), `sse` (HTTP Server-Sent Events), and `fastmcp` (in-process Python import). All three are configured in `config/mcp_servers.yaml`.

### Rationale

`langchain-mcp 0.2.1` and `fastmcp 3.2.0` (already in pyproject.toml) handle the underlying MCP protocol. The aggregator is an adapting wrapper that normalizes the tool discovery interface regardless of which transport is used.

- **stdio**: standard for CLI-based MCP servers (e.g., filesystem, git tools)
- **sse**: standard for remote/cloud MCP servers over HTTP
- **fastmcp**: for in-process custom tools co-located with helios-agent

### Alternatives Considered

- Using `langchain-mcp` MultiClient directly: locks in LangChain's interface; harder to normalize tool metadata independently
- Single transport only: too restrictive; real deployments mix all three

---

## 3. Session Serialization in Redis

### Decision

Serialize `AgentState` to JSON using a custom encoder that handles `datetime`, `dataclass`, and nested dataclass fields. Deserialize by reconstructing nested dataclasses explicitly.

### Rationale

`json.dumps(state.__dict__, default=str)` (from the user's sketch) is insufficient — it stringifies datetimes instead of making them round-trippable. The implementation needs:

- A recursive `dataclass_to_dict()` helper that converts `datetime` to ISO string
- A `dict_to_agent_state()` reconstructor that parses ISO strings back to `datetime`

Redis stores the result as a UTF-8 string. TTL is operator-configurable (default: 3600 seconds).

### Alternatives Considered

- **pickle**: fast, but insecure for untrusted data; not JSON-queryable for debug tooling
- **msgpack**: compact but adds a dependency; no benefit over JSON at this scale
- **Pydantic serialization**: requires converting AgentState to Pydantic, which conflicts with LangGraph's dataclass requirement

---

## 4. Concurrent Session Write Serialization

### Decision

Use a Redis-backed per-session advisory lock (`SET session:lock:{id} NX EX 30`) to serialize writes. A request that cannot acquire the lock within 30 seconds returns a `409 Conflict` with `error_code: "session_locked"`.

### Rationale

Clarification Q4 confirmed: one request at a time per session; subsequent requests wait or timeout. Redis `SET NX EX` is atomic, available in `redis-py 5.x`, and avoids any Python-level threading concerns since FastAPI is async.

Lock TTL = 30 seconds (matches the configurable session-lock timeout from FR-026). Lock is released on `finally` in the request handler regardless of success or failure.

### Alternatives Considered

- asyncio.Lock per session in-process: breaks across multi-replica deployments (violates stateless FastAPI constraint)
- Postgres advisory locks: adds a DB dependency not present in v1
- No locking: rejected per spec clarification

---

## 5. LLM Provider Integration (OpenRouter)

### Decision

The `openrouter-llm` package is already available as a custom Docker image. Call it via `httpx.AsyncClient` with the OpenRouter API format (`POST /chat/completions`). Wrap in a `LLMClient` class with `async def predict(messages, model) -> str` that raises `LLMProviderError` on all non-200 responses.

### Rationale

Clarification Q1 confirmed: LLM unavailability must return an immediate failure response with provider status. The `LLMClient` wrapper catches all `httpx.HTTPError`, `asyncio.TimeoutError`, and non-2xx responses and raises `LLMProviderError(error_code="provider_unavailable", message=..., detail=...)` for uniform surfacing via the error response format.

### Alternatives Considered

- Using LangChain's ChatOpenAI with `openai_api_base` override: works but binds the API to LangChain version bumps
- Direct `openai` SDK: same concern; also harder to inject into LangGraph nodes without global state

---

## 6. Retry Backoff Parameters

### Decision

Exponential backoff with jitter per clarification Q3:

- Delay = `2^attempt` seconds + `random.uniform(0, 0.5)` seconds
- Attempt 0 → ~1s, Attempt 1 → ~2s, Attempt 2 → ~4s
- Max retries = 3 (configurable via `ToolDefinition.retry_count`)
- Max retry delay cap = 10s (prevents runaway waits on high attempt counts)

### Rationale

This mirrors the industry-standard full-jitter pattern (AWS builders' library). Jitter prevents thundering-herd retry storms when multiple sessions hit the same tool simultaneously.

### Alternatives Considered

- Fixed 500ms interval: simpler but risks synchronized retries at scale
- `tenacity` library: battle-tested but adds a dependency for logic that is ~10 lines

---

## 7. Error Response Structure

### Decision

All error responses use this JSON envelope, per clarification Q2:

```json
{
  "error_code": "string (snake_case, e.g. validation_error, provider_unavailable, tool_timeout)",
  "message": "string (human-readable summary)",
  "severity_level": "string (info | warning | error | critical)",
  "detail":  "<optional: object or string with extended diagnostic info>",
  "recovery_hint": "<optional: string with action the client can take>"
}
```

FastAPI returns this as the `detail` field of `HTTPException` responses, or directly as the response body for non-2xx chat outcomes.

### Rationale

Consistent machine-parseable errors enable client retry logic, user-facing messaging, and operator alerting without string matching. Matches the OpenAI/Anthropic API error envelope convention that clients already expect.

### Alternatives Considered

- RFC 7807 Problem Details: more complex; no benefit over this simpler structure for v1

---

## 8. Tool Discovery Timing

### Decision

Discover all MCP tools once at application startup in the FastAPI `lifespan` handler, before `yield`. Tool catalog is static for the lifetime of the process. Adding/removing tools requires a service restart (FR-007 as clarified).

### Rationale

Clarification Q5 confirmed: static startup catalog. This simplifies testing (no race conditions on catalog state), satisfies the constitution's Hard Constraint #4 ("MCP servers must be available at startup"), and keeps the hot-path logic free of discovery lock contention.

### Alternatives Considered

- Periodic background refresh: adds complexity, race conditions in tests, contention between in-flight requests and catalog updates
- On-demand refresh endpoint: deferred to v2 as optional operator convenience

---

## 9. Graph Node Count & Bounded Complexity

### Decision

The agent graph uses exactly 8 nodes: `think`, `decide_action`, `invoke_tool`, `tool_result`, `evaluate_result`, `direct_response`, `error`, `respond`. This is within the constitution's ≤10 decision nodes limit.

### Rationale

Constitution Principle III requires bounded graph complexity (≤10 nodes). The user-supplied graph specification uses 8 nodes with 3 conditional routing functions. All decision branches (use_tool / direct_response / retry / fallback / error) are modelled as explicit edges — no open-ended loops.

### Alternatives Considered

- Collapsing `tool_result` + `evaluate_result` into one node: simpler, but conflates I/O parsing with business logic; harder to test independently

---

## 10. Project Layout Confirmation

### Decision

Use the flat `src/mcp_agent/` layout inside the existing `helios-agent` repo root (not a new sub-package). The project name in `pyproject.toml` is `helios-agent`; the importable package is `mcp_agent`.

### Rationale

The technical requirements specify `src/mcp_agent/` as the source root. All existing dependencies (`fastapi`, `langgraph`, `langchain-mcp`, `fastmcp`, `redis`, `loguru`, `sqlmodel`) are already present in `pyproject.toml`. No new top-level packages need to be added.

### Alternatives Considered

- Separate sub-package under `packages/`: over-engineered for a single-service agent with no shared lib requirements in v1
