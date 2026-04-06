# API Contract: MCP Agent Service

**Feature**: `001-mcp-langgraph-agent`  
**Date**: 2026-04-06  
**Version**: v1  
**Base URL**: `/api`  
**Content-Type**: `application/json`

---

## Common Types

### ErrorResponse

All non-2xx responses and agent-level failures return this envelope.

```json
{
  "error_code": "string",
  "message": "string",
  "severity_level": "info | warning | error | critical",
  "detail": "<object | string | null>",
  "recovery_hint": "<string | null>"
}
```

### ToolCallSummary

```json
{
  "tool_id": "string",
  "status": "success | failure | retry | fallback | timeout",
  "duration_ms": "integer",
  "fallback_used": "<string | null>"
}
```

---

## Endpoints

### POST /api/chat

Submit a user message and receive an agent response.

**Request**

```json
{
  "message": "string (1–4096 chars, required)",
  "session_id": "<uuid4 string | null>",
  "metadata": "<object | {}>"
}
```

**Response 200 OK**

```json
{
  "session_id": "uuid4 string",
  "response": "string",
  "success": "boolean",
  "turn_count": "integer",
  "tool_calls": "[ToolCallSummary]",
  "duration_ms": "integer",
  "error": "<ErrorResponse | null>",
  "metadata": "<object | {}>"
}
```

> `success: false` with `error` populated indicates an agent-level failure (tool failure, LLM unavailability, etc.). The HTTP status is still `200`. Use `error.error_code` to distinguish failure kinds.

**Response 422 Unprocessable Entity** — validation failure

```json
{
  "error_code": "validation_error",
  "message": "Message must be between 1 and 4096 characters.",
  "severity_level": "error",
  "detail": { "field": "message", "actual_length": 5000 },
  "recovery_hint": "Shorten the message to 4096 characters or fewer."
}
```

**Response 404 Not Found** — session not found or expired

```json
{
  "error_code": "session_not_found | session_expired",
  "message": "Session abc123 was not found.",
  "severity_level": "warning",
  "detail": null,
  "recovery_hint": "Omit session_id to start a new session."
}
```

**Response 409 Conflict** — concurrent write lock timeout

```json
{
  "error_code": "session_locked",
  "message": "Session abc123 is currently processing another request.",
  "severity_level": "warning",
  "detail": { "lock_timeout_seconds": 30 },
  "recovery_hint": "Retry after the current request completes."
}
```

**Response 422 Unprocessable Entity** — turn limit exceeded

```json
{
  "error_code": "session_turn_limit_exceeded",
  "message": "Session abc123 has reached its maximum of 5 turns.",
  "severity_level": "error",
  "detail": { "turn_count": 5, "max_turns": 5 },
  "recovery_hint": "Start a new session."
}
```

**Response 503 Service Unavailable** — LLM provider unavailable

```json
{
  "error_code": "provider_unavailable",
  "message": "The language model provider is currently unavailable.",
  "severity_level": "critical",
  "detail": { "provider": "openrouter", "http_status": 503 },
  "recovery_hint": "Retry in a few minutes. If the problem persists, contact support."
}
```

---

### GET /api/session/{session_id}

Retrieve session summary and conversation history.

**Path Parameters**: `session_id` (uuid4 string)

**Response 200 OK**

```json
{
  "session_id": "string",
  "created_at": "ISO 8601 datetime",
  "last_activity": "ISO 8601 datetime",
  "turn_count": "integer",
  "conversation_history": [
    {
      "role": "user | assistant",
      "content": "string",
      "timestamp": "ISO 8601 datetime"
    }
  ]
}
```

**Response 404 Not Found**

```json
{
  "error_code": "session_not_found",
  "message": "Session abc123 was not found.",
  "severity_level": "warning",
  "detail": null,
  "recovery_hint": null
}
```

---

### DELETE /api/session/{session_id}

Remove a session from the store.

**Path Parameters**: `session_id` (uuid4 string)

**Response 200 OK**

```json
{
  "message": "Session deleted.",
  "session_id": "string"
}
```

> Returns `200` even if the session did not exist (idempotent delete).

---

### GET /api/debug/trace/{session_id}

Retrieve execution trace for a session.

**Path Parameters**: `session_id` (uuid4 string)

**Response 200 OK**

```json
{
  "session_id": "string",
  "turns": [
    {
      "turn_number": "integer",
      "timestamp": "ISO 8601 datetime",
      "decision": "use_tool | direct_response | error",
      "tool_calls": "[ToolCallSummary]",
      "llm_thought": "string | null",
      "duration_ms": "integer",
      "outcome": "success | failure"
    }
  ]
}
```

**Response 404 Not Found** — same structure as session not found.

---

### GET /api/debug/metrics

Return aggregate service metrics.

**Response 200 OK**

```json
{
  "sessions_total": "integer",
  "turns_total": "integer",
  "tool_calls_total": "integer",
  "tool_failures_total": "integer",
  "tool_fallbacks_total": "integer",
  "llm_calls_total": "integer",
  "llm_errors_total": "integer",
  "avg_turn_duration_ms": "number",
  "p95_turn_duration_ms": "number"
}
```

---

### GET /api/health

Service health check.

**Response 200 OK** — healthy

```json
{
  "status": "healthy | degraded",
  "components": {
    "redis": "connected | disconnected",
    "mcp_servers": {
      "<server_name>": "ready | unavailable"
    }
  },
  "timestamp": "ISO 8601 datetime"
}
```

**Response 503 Service Unavailable** — critical dependency unavailable

```json
{
  "status": "unhealthy",
  "components": {
    "redis": "disconnected",
    "mcp_servers": {}
  },
  "timestamp": "ISO 8601 datetime"
}
```

---

## Constraints

- All timestamps are UTC ISO 8601 (`2026-04-06T12:00:00Z`)
- `session_id` is always a UUID4 string; other formats are rejected with `validation_error`
- Request bodies must be valid JSON with `Content-Type: application/json`
- No authentication headers are required in v1
- The service does not stream; all responses are returned atomically
