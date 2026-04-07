"""
In-memory trace buffer for diagnostic log collection.

Implements a ring buffer (circular buffer) that captures structured log records
bound with session_id, useful for per-session debugging and observability.
"""

import threading
from collections import deque
from datetime import datetime
from typing import Any


class TraceBuffer:
    """
    Thread-safe ring buffer for capturing trace events.
    
    Holds up to 1000 events per session, storing structured log records
    with timestamp, level, message, and context bindings. Used by loguru
    sink callback to populate traces for GET /api/debug/trace/{session_id}.
    """
    
    def __init__(self, maxlen: int = 1000):
        """
        Initialize the trace buffer.
        
        Args:
            maxlen: Maximum number of events to retain in ring buffer (default: 1000)
        """
        self.buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.lock = threading.Lock()
    
    def add_event(
        self,
        session_id: str | None,
        timestamp: datetime,
        level: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Add a trace event to the buffer.
        
        Args:
            session_id: Session identifier if available, or None
            timestamp: Event timestamp
            level: Log level (DEBUG, INFO, WARNING, ERROR, etc.)
            message: Log message text
            context: Optional context dictionary (e.g., from loguru extra bindings)
        """
        if not session_id:
            return  # Only trace events with session_id
        
        event = {
            "session_id": session_id,
            "timestamp": timestamp.isoformat(),
            "level": level,
            "message": message,
            "context": context or {},
        }
        
        with self.lock:
            self.buffer.append(event)
    
    def get_traces_by_session_id(self, session_id: str) -> list[dict[str, Any]]:
        """
        Retrieve all trace events for a given session.
        
        Args:
            session_id: Session identifier to filter by
            
        Returns:
            List of trace event dictionaries ordered by timestamp
        """
        with self.lock:
            events = [e for e in self.buffer if e.get("session_id") == session_id]
        return events
    
    def clear(self) -> None:
        """Clear all trace events from the buffer."""
        with self.lock:
            self.buffer.clear()
    
    def loguru_sink(self, message: dict[str, Any]) -> None:
        """
        Loguru sink callback for integrating with the logging system.
        
        Expected to be registered as a loguru sink. Extracts session_id
        from the record's context (extra dict) and adds the event to the buffer.
        
        Args:
            message: Loguru record message dictionary with 'record' and 'message' keys
        """
        record = message.get("record", {})
        extra = record.get("extra", {})
        session_id = extra.get("session_id")
        
        # Only trace events with session_id binding
        if not session_id:
            return
        
        timestamp = datetime.fromisoformat(record.get("time", {}).get("repr", ""))
        level = record.get("level", {}).get("name", "INFO")
        text = message.get("message", "")
        
        # Build context from extra bindings (excluding session_id to avoid duplication)
        context = {k: v for k, v in extra.items() if k != "session_id"}
        
        self.add_event(
            session_id=session_id,
            timestamp=timestamp,
            level=level,
            message=text,
            context=context,
        )
