# Data Model: MCP-Integrated LangGraph Agent

**Feature**: `001-mcp-langgraph-agent`  
**Date**: 2026-04-06  
**Source**: spec.md entities + clarifications + research.md

---

## Storage Overview

| Store | Technology | Purpose |
|-------|-----------|---------|
| Session state | Redis (ephemeral, TTL-bound) | AgentState, conversation history, tool records |
| Session lock | Redis (TTL-bound key) | Per-session write serialization |
| Tool catalog | In-process dict (process-scoped) | Normalized MCP tool definitions, populated at startup |
| Structured logs | loguru → stdout / file | Execution traces, decisions, errors |

No relational database is used in v1. `sqlmodel` and `alembic` in `pyproject.toml` are available for a future audit-log phase.

---

## Core Entities

### 1. AgentState `(agent/state.py)` — Redis-persisted

The primary unit of session state. Serialized to JSON and stored at Redis key `session:{session_id}`.

```python
@dataclass
class AgentState:
    # Identity
    session_id: str                           # UUID4 string; created on first turn
    created_at: datetime                      # ISO 8601, UTC
    last_activity: datetime                   # Updated on every turn

    # Conversation
    messages: list[Message]                   # Ordered, append-only; last 5 used for context window
    turn_count: int                           # Incremented before graph execution; max = settings.max_turns (default 5)

    # Current execution (reset each turn)
    current_input: str                        # Validated user message (≤4096 chars)
    current_thought: str | None               # LLM chain-of-thought from node_think
    current_decision: str | None              # "use_tool" | "direct_response" | "error"

    # Tool execution (reset each turn)
    selected_tool_id: str | None              # Fully-qualified "server.tool_name"
    tool_calls_this_turn: list[ToolCallRecord]
    current_tool_output: Any | None           # Raw tool result for node_evaluate_result

    # Error state (reset each turn)
    last_error: str | None
    error_count: int                          # Cumulative across turns

    # Startup-loaded, not persisted per-turn
    available_tools: list[dict]               # Snapshot of ToolDefinition.__dict__ at startup
    metadata: dict                            # Client metadata from ChatRequest
```

**Validation rules**:
- `session_id`: matches UUID4 regex; rejected as `validation_error` otherwise
- `current_input`: 1–4096 characters; empty or oversized rejected before graph execution
- `turn_count`: if `>= settings.max_turns` (default 5), request rejected with `error_code: "session_turn_limit_exceeded"`
- `last_activity`: checked against session TTL on load; expired sessions return `404` with `error_code: "session_expired"`

**State transitions**:
```
(new request)
    │
    ▼
[LOAD or CREATE session] ──── expired? ──→ 404 session_expired
    │
    ▼
[ACQUIRE lock: session:lock:{id}] ──── timeout? ──→ 409 session_locked
    │
    ▼
[EXECUTE graph: think → decide_action → ...]
    │
    ├── use_tool ──→ invoke_tool → tool_result → evaluate_result
    │                   ├── retry (≤3x, exponential backoff)
    │                   ├── fallback tool
    │                   └── tool_failure (error node)
    │
    ├── direct_response ──→ respond
    │
    └── error ──→ respond (with error envelope)
    │
    ▼
[SAVE state to Redis, RELEASE lock]
    │
    ▼
[RETURN ChatResponse]
```

---

### 2. Message `(agent/state.py)` — embedded in AgentState.messages

```python
@dataclass
class Message:
    role: str          # "user" | "assistant"
    content: str       # Full message text
    timestamp: datetime
    tool_calls: list[dict]    # Serialized ToolCallRecord references for this turn
    metadata: dict            # Arbitrary per-message metadata
```

---

### 3. ToolCallRecord `(agent/state.py)` — embedded in AgentState.tool_calls_this_turn

```python
@dataclass
class ToolCallRecord:
    tool_id: str              # Fully-qualified "server.tool_name"
    input: dict               # Input sent to the tool
    output: Any               # Raw output (or None on failure)
    duration_ms: int          # Wall-clock time for this attempt
    status: str               # "success" | "failure" | "retry" | "fallback" | "timeout"
    error: str | None         # Error message if status != "success"
    retry_count: int          # Number of retries before this result (0 = first attempt succeeded)
    fallback_used: str | None # tool_id of the fallback tool if fallback was triggered
```

---

### 4. ToolDefinition `(mcp/registry.py)` — in-process, startup-loaded

```python
@dataclass
class ToolDefinition:
    id: str                   # "server_name.tool_name" (globally unique)
    name: str                 # Tool's own name as declared by MCP server
    description: str          # Human-readable; used in LLM prompt
    source: str               # MCP server name (matches mcp_servers.yaml key)
    input_schema: dict        # JSON Schema for input validation
    output_schema: dict       # JSON Schema for output validation
    async_capable: bool       # Whether tool supports async invocation
    timeout_ms: int           # Per-tool timeout (default: 5000)
    retry_count: int          # Max retries on transient failure (default: 3)
    fallback_tools: list[str] # Ordered list of fallback tool IDs
```

**Catalog lifecycle**:
- Populated once in `lifespan()` startup handler
- Immutable during process lifetime (FR-007)
- Serialized snapshot (`__dict__`) stored in `AgentState.available_tools` for session-level reference

---

### 5. ToolExecutionResult `(mcp/executors.py)` — transient, not persisted

```python
@dataclass
class ToolExecutionResult:
    tool_id: str
    status: str               # "success" | "failure" | "timeout" | "fallback"
    output: Any               # Successful result or None
    error: str | None
    duration_ms: int
    retry_count: int
    fallback_used: str | None
```

---

### 6. Error Response Envelope `(api/models.py)` — wire format

```python
class ErrorResponse(BaseModel):
    error_code: str           # snake_case identifier, e.g. "validation_error"
    message: str              # Human-readable summary for client display
    severity_level: str       # "info" | "warning" | "error" | "critical"
    detail: dict | str | None = None    # Extended diagnostic payload
    recovery_hint: str | None = None    # Action the client can take
```

**Canonical error codes**:
| `error_code` | HTTP status | Trigger |
|---|---|---|
| `validation_error` | 422 | Empty message, message too long, bad session ID format |
| `session_not_found` | 404 | Session ID doesn't exist in Redis |
| `session_expired` | 404 | Session TTL elapsed |
| `session_locked` | 409 | Concurrent write timeout (FR-026) |
| `session_turn_limit_exceeded` | 422 | Turn count ≥ max_turns |
| `tool_timeout` | 200* | Tool timed out after retries (surfaced in response body) |
| `tool_failure` | 200* | Tool failed with no recovery path |
| `provider_unavailable` | 503 | LLM provider unreachable/quota exceeded (FR-024) |
| `provider_timeout` | 504 | LLM provider did not respond within budget |
| `internal_error` | 500 | Unexpected exception in graph or handlers |

*Tool errors are returned as `200 OK` with `success: false` in the `ChatResponse` body per standard agent API convention.

---

### 7. ChatRequest / ChatResponse `(api/models.py)` — wire format

```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    session_id: str | None = None          # UUID4; None = new session
    metadata: dict = Field(default_factory=dict)

class ChatResponse(BaseModel):
    session_id: str
    response: str                          # Agent's natural-language answer
    success: bool                          # False if agent hit an unrecoverable error
    turn_count: int
    tool_calls: list[ToolCallSummary]      # Serialized tool invocations for this turn
    duration_ms: int
    error: ErrorResponse | None = None    # Populated when success=False
    metadata: dict = Field(default_factory=dict)

class ToolCallSummary(BaseModel):
    tool_id: str
    status: str
    duration_ms: int
    fallback_used: str | None = None
```

---

## Redis Key Schema

| Key pattern | Type | TTL | Description |
|---|---|---|---|
| `session:{session_id}` | String (JSON) | Configurable (default 3600s) | Serialized AgentState |
| `session:lock:{session_id}` | String | 30s | Per-session write lock (SET NX EX) |

---

## Serialization Notes

- All `datetime` fields serialize to ISO 8601 UTC strings (`2026-04-06T12:00:00Z`)
- `Any` typed fields (tool output) are serialized with `json.dumps(..., default=repr)` — non-serializable objects become their `repr()` string
- `AgentState.available_tools` is a list of `dict` (not `ToolDefinition` objects) to avoid re-importing the registry module during deserialization
