"""
In-process metrics store for aggregate observability.

Tracks counters for sessions, turns, tool calls, LLM invocations, and timing.
Thread-safe via threading.Lock for use across async contexts.
"""

import threading
from typing import Any


class MetricsStore:
    """
    Thread-safe metrics store for aggregate agent observability.
    
    Tracks counters for total sessions, turns, tool calls, failures,
    LLM invocations, and cumulative duration for P99 latency tracking.
    Populated by chat_handler and ToolExecutor; read via GET /api/debug/metrics.
    """
    
    def __init__(self):
        """Initialize metrics store with all counters at zero."""
        self.lock = threading.Lock()
        
        self.total_sessions: int = 0
        """Total number of sessions created"""
        
        self.total_turns: int = 0
        """Total number of conversation turns across all sessions"""
        
        self.tool_calls: int = 0
        """Total number of tool invocations"""
        
        self.tool_failures: int = 0
        """Total number of tool execution failures"""
        
        self.llm_invocations: int = 0
        """Total number of LLM API calls"""
        
        self.total_duration_ms: int = 0
        """Cumulative processing duration in milliseconds"""
    
    def increment_sessions(self, count: int = 1) -> None:
        """
        Increment the session counter.
        
        Args:
            count: Number to increment by (default: 1)
        """
        with self.lock:
            self.total_sessions += count
    
    def increment_turns(self, count: int = 1) -> None:
        """
        Increment the turn counter.
        
        Args:
            count: Number to increment by (default: 1)
        """
        with self.lock:
            self.total_turns += count
    
    def increment_tool_calls(self, count: int = 1) -> None:
        """
        Increment the tool call counter.
        
        Args:
            count: Number to increment by (default: 1)
        """
        with self.lock:
            self.tool_calls += count
    
    def increment_tool_failures(self, count: int = 1) -> None:
        """
        Increment the tool failure counter.
        
        Args:
            count: Number to increment by (default: 1)
        """
        with self.lock:
            self.tool_failures += count
    
    def increment_llm_invocations(self, count: int = 1) -> None:
        """
        Increment the LLM invocation counter.
        
        Args:
            count: Number to increment by (default: 1)
        """
        with self.lock:
            self.llm_invocations += count
    
    def add_duration_ms(self, duration_ms: int) -> None:
        """
        Add to cumulative duration.
        
        Args:
            duration_ms: Duration in milliseconds to add
        """
        with self.lock:
            self.total_duration_ms += duration_ms
    
    def get_snapshot(self) -> dict[str, Any]:
        """
        Get a thread-safe snapshot of all metrics.
        
        Returns:
            Dictionary containing all counter values and calculated properties
        """
        with self.lock:
            avg_duration_ms = (
                self.total_duration_ms / self.total_turns
                if self.total_turns > 0
                else 0
            )
            
            return {
                "total_sessions": self.total_sessions,
                "total_turns": self.total_turns,
                "tool_calls": self.tool_calls,
                "tool_failures": self.tool_failures,
                "llm_invocations": self.llm_invocations,
                "total_duration_ms": self.total_duration_ms,
                "avg_duration_ms": int(avg_duration_ms),
            }
    
    def reset(self) -> None:
        """Reset all metrics to zero."""
        with self.lock:
            self.total_sessions = 0
            self.total_turns = 0
            self.tool_calls = 0
            self.tool_failures = 0
            self.llm_invocations = 0
            self.total_duration_ms = 0
