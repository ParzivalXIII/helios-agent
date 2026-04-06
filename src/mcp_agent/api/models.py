"""
Pydantic models for REST API request/response bodies.

Defines all data models used in API contracts, with validation and JSON schema.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request body for POST /api/chat endpoint."""

    session_id: str | None = Field(
        default=None,
        description="UUID4 session ID. If None, a new session is created.",
    )
    message: str = Field(
        ..., min_length=1, max_length=4096, description="User message (1–4096 chars)."
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Optional client metadata (user_id, session_name, etc.).",
    )


class ToolCallSummary(BaseModel):
    """Summary of a tool call for API response."""

    tool_id: str = Field(..., description="Fully-qualified tool identifier.")
    status: Literal["success", "failure", "retry", "fallback", "timeout"] = Field(
        ..., description="Tool execution status."
    )
    duration_ms: int = Field(default=0, description="Execution time in milliseconds.")
    fallback_used: str | None = Field(
        default=None, description="Fallback tool_id if used, or None."
    )


class ChatResponse(BaseModel):
    """Response body for successful POST /api/chat."""

    session_id: str = Field(..., description="Session UUID4.")
    response: str = Field(..., description="Final LLM-generated response.")
    success: bool = Field(
        default=True, description="True if successful; False if error occurred."
    )
    turn_count: int = Field(..., description="Total turns in this session.")
    tool_calls: list[ToolCallSummary] = Field(
        default_factory=list, description="Tool calls made this turn."
    )
    duration_ms: int = Field(..., description="Total request processing time.")
    error: "ErrorResponse | None" = Field(
        default=None, description="Error details if success is False."
    )
    metadata: dict = Field(
        default_factory=dict, description="Client metadata echoed back."
    )


class ErrorResponse(BaseModel):
    """Response body for errors."""

    error_code: str = Field(
        ...,
        description="Machine-readable error code (e.g., 'session_not_found', 'validation_error').",
    )
    message: str = Field(..., description="Human-readable error message.")
    severity_level: Literal["info", "warning", "error", "critical"] = Field(
        default="error", description="Severity level of the error."
    )
    detail: str | None = Field(
        default=None, description="Additional error details."
    )
    recovery_hint: str | None = Field(
        default=None, description="Suggested recovery action for the client."
    )


class SessionModel(BaseModel):
    """Response body for GET /api/session/{id}."""

    id: str = Field(..., description="Session UUID4.")
    turn_count: int = Field(..., description="Number of turns in this session.")
    messages: list[dict] = Field(
        default_factory=list, description="Conversation messages."
    )
    last_activity: datetime = Field(
        ..., description="Last activity timestamp (ISO 8601)."
    )
    state: dict = Field(default_factory=dict, description="Full AgentState JSON.")


class HealthResponse(BaseModel):
    """Response body for GET /api/health."""

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        ..., description="Overall service health status."
    )
    redis: Literal["up", "down"] = Field(
        default="down", description="Redis connectivity status."
    )
    llm_provider: Literal["up", "down"] = Field(
        default="down", description="LLM provider connectivity status."
    )
    tool_count: int = Field(default=0, description="Number of available tools.")
    timestamp: datetime = Field(..., description="Response timestamp (ISO 8601).")
