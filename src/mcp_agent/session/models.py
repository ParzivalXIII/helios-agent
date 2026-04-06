"""
Session serialization helpers.

Provides dataclass_to_dict() and dict_to_agent_state() for round-tripping
AgentState to/from JSON stored in Redis.
"""

import json
from datetime import datetime
from typing import Any

from mcp_agent.agent.state import AgentState, Message, ToolCallRecord


def dataclass_to_dict(state: AgentState) -> dict:
    """
    Convert an AgentState dataclass to a dictionary suitable for JSON serialization.
    
    Handles:
    - Nested Message and ToolCallRecord dataclasses
    - datetime objects serialized to ISO 8601 UTC strings
    - Non-serializable objects converted via repr()
    
    Args:
        state: The AgentState to serialize
        
    Returns:
        Dictionary representation ready for JSON serialization
    """
    def serialize_value(val: Any) -> Any:
        """Recursively serialize values, handling datetime and non-serializable types."""
        if isinstance(val, datetime):
            # ISO 8601 UTC format: "2026-04-06T12:00:00Z"
            return val.isoformat() + "Z" if not val.isoformat().endswith("Z") else val.isoformat()
        elif isinstance(val, Message):
            return {
                "role": val.role,
                "content": val.content,
                "created_at": serialize_value(val.created_at),
            }
        elif isinstance(val, ToolCallRecord):
            return {
                "tool_id": val.tool_id,
                "status": val.status,
                "output": serialize_value(val.output),
                "error": val.error,
                "attempt_count": val.attempt_count,
                "duration_ms": val.duration_ms,
                "fallback_used": val.fallback_used,
            }
        elif isinstance(val, list):
            return [serialize_value(item) for item in val]
        elif isinstance(val, dict):
            return {k: serialize_value(v) for k, v in val.items()}
        elif val is None:
            return None
        else:
            # For non-serializable objects, use repr()
            try:
                json.dumps(val)  # Test if directly serializable
                return val
            except (TypeError, ValueError):
                return repr(val)
    
    return {
        "session_id": state.session_id,
        "created_at": serialize_value(state.created_at),
        "last_activity": serialize_value(state.last_activity),
        "messages": [serialize_value(msg) for msg in state.messages],
        "turn_count": state.turn_count,
        "current_input": state.current_input,
        "current_thought": state.current_thought,
        "current_decision": state.current_decision,
        "selected_tool_id": state.selected_tool_id,
        "tool_calls_this_turn": [serialize_value(tc) for tc in state.tool_calls_this_turn],
        "current_tool_output": serialize_value(state.current_tool_output),
        "last_error": state.last_error,
        "error_count": state.error_count,
        "available_tools": state.available_tools,
        "metadata": state.metadata,
    }


def dict_to_agent_state(data: dict) -> AgentState:
    """
    Convert a dictionary (from JSON) back to an AgentState dataclass.
    
    Handles:
    - ISO 8601 UTC strings converted back to datetime objects
    - Nested dicts converted back to Message and ToolCallRecord dataclasses
    
    Args:
        data: Dictionary representation from Redis JSON
        
    Returns:
        Reconstructed AgentState
        
    Raises:
        ValueError: If required fields are missing or data is malformed
        KeyError: If expected keys are not found
    """
    def deserialize_datetime(value: str | None) -> datetime | None:
        """Parse ISO 8601 UTC string back to datetime."""
        if value is None:
            return None
        if isinstance(value, str):
            # Handle both with and without trailing 'Z'
            iso_str = value.rstrip("Z")
            return datetime.fromisoformat(iso_str)
        raise ValueError(f"Expected string or None for datetime, got {type(value)}")
    
    def deserialize_message(msg_dict: dict) -> Message:
        """Reconstruct Message from dict."""
        return Message(
            role=msg_dict["role"],
            content=msg_dict["content"],
            created_at=deserialize_datetime(msg_dict["created_at"]),
        )
    
    def deserialize_tool_call(tc_dict: dict) -> ToolCallRecord:
        """Reconstruct ToolCallRecord from dict."""
        return ToolCallRecord(
            tool_id=tc_dict["tool_id"],
            status=tc_dict["status"],
            output=tc_dict.get("output"),
            error=tc_dict.get("error"),
            attempt_count=tc_dict.get("attempt_count", 1),
            duration_ms=tc_dict.get("duration_ms", 0),
            fallback_used=tc_dict.get("fallback_used", False),
        )
    
    messages = [
        deserialize_message(msg) for msg in data.get("messages", [])
    ]
    
    tool_calls_this_turn = [
        deserialize_tool_call(tc) for tc in data.get("tool_calls_this_turn", [])
    ]
    
    return AgentState(
        session_id=data["session_id"],
        created_at=deserialize_datetime(data["created_at"]),
        last_activity=deserialize_datetime(data["last_activity"]),
        messages=messages,
        turn_count=data.get("turn_count", 0),
        current_input=data.get("current_input", ""),
        current_thought=data.get("current_thought"),
        current_decision=data.get("current_decision"),
        selected_tool_id=data.get("selected_tool_id"),
        tool_calls_this_turn=tool_calls_this_turn,
        current_tool_output=data.get("current_tool_output"),
        last_error=data.get("last_error"),
        error_count=data.get("error_count", 0),
        available_tools=data.get("available_tools", []),
        metadata=data.get("metadata", {}),
    )
