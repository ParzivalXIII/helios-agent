"""
Tool execution engine with retry and fallback support.

Handles invocation of MCP tools with automatic retry on transient failures
and fallback tool chain support.
"""

import asyncio
import random
import time
from typing import Any

from loguru import logger

from mcp_agent.agent.state import ToolCallRecord
from mcp_agent.mcp.registry import ToolDefinition, ToolRegistry


class ToolExecutor:
    """
    Executes tools with retry and fallback support.
    
    Manages tool invocation including:
    - Timeout enforcement
    - Automatic retry with exponential backoff
    - Fallback tool invocation on failure
    - Result tracking and error recording
    """
    
    def __init__(self, registry: ToolRegistry, max_retries: int = 3):
        """
        Initialize the tool executor.
        
        Args:
            registry: ToolRegistry containing available tools.
            max_retries: Maximum retry attempts per tool (default: 3).
        """
        self.registry = registry
        self.max_retries = max_retries
        self.logger = logger.bind(component="ToolExecutor")
    
    async def execute(self, tool_id: str, arguments: dict[str, Any]) -> ToolCallRecord:
        """
        Execute a tool with retry and fallback support.
        
        Enforces per-tool timeout via asyncio.wait_for; retries transient failures
        with exponential backoff (1s, 2s, 4s base with ±0-500ms jitter); on permanent
        failure, attempts configured fallback (max 1 level deep).
        
        Args:
            tool_id: Fully-qualified tool identifier (e.g., "server.tool_name").
            arguments: Input arguments for the tool.
            
        Returns:
            ToolCallRecord with execution status and result/error information.
        """
        start_time = time.time()
        
        # Get tool definition
        tool_def = self.registry.get(tool_id)
        if not tool_def:
            self.logger.error(f"Tool not found in registry: {tool_id}")
            return ToolCallRecord(
                tool_id=tool_id,
                status="failed",
                error=f"Tool not found: {tool_id}",
                attempt_count=0,
                duration_ms=int((time.time() - start_time) * 1000)
            )
        
        # Try to execute the tool with retries
        record = await self._execute_with_retries(tool_def, arguments)
        
        # If failed, try fallback tool (max 1 level deep)
        if record.status == "failed" and tool_def.fallback_tool_id:
            self.logger.info(f"Attempting fallback tool: {tool_def.fallback_tool_id}")
            fallback_def = self.registry.get(tool_def.fallback_tool_id)
            if fallback_def:
                record = await self._execute_with_retries(fallback_def, arguments)
                record.fallback_used = True
                record.tool_id = tool_id  # Keep original tool_id in the record
        
        # Record total duration
        record.duration_ms = int((time.time() - start_time) * 1000)
        
        return record
    
    async def _execute_with_retries(
        self,
        tool_def: ToolDefinition,
        arguments: dict[str, Any]
    ) -> ToolCallRecord:
        """
        Execute a tool with automatic retry on transient failures.
        
        Implements exponential backoff: base delays 2^0=1s, 2^1=2s, 2^2=4s
        with ±0-500ms jitter per attempt, capped at 10s total per attempt.
        
        Args:
            tool_def: Tool definition to execute.
            arguments: Tool input arguments.
            
        Returns:
            ToolCallRecord with result or error.
        """
        record = ToolCallRecord(
            tool_id=tool_def.id,
            status="pending",
            attempt_count=0
        )
        
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            record.attempt_count = attempt
            
            try:
                self.logger.debug(
                    f"Tool execution attempt {attempt}/{self.max_retries}: {tool_def.id}"
                )
                
                # Execute tool with timeout enforcement
                result = await asyncio.wait_for(
                    self._invoke_tool(tool_def, arguments),
                    timeout=tool_def.timeout_ms / 1000.0
                )
                
                record.status = "success"
                record.output = result
                self.logger.info(f"Tool {tool_def.id} executed successfully")
                return record
                
            except asyncio.TimeoutError:
                last_error = f"Tool execution timeout after {tool_def.timeout_ms}ms"
                self.logger.warning(f"Tool {tool_def.id} timed out on attempt {attempt}")
                
                if attempt < self.max_retries:
                    await self._exponential_backoff(attempt)
                    record.status = "retried"
                    
            except Exception as e:
                last_error = str(e)
                self.logger.warning(f"Tool {tool_def.id} failed on attempt {attempt}: {e}")
                
                if attempt < self.max_retries:
                    await self._exponential_backoff(attempt)
                    record.status = "retried"
        
        # All retries exhausted
        record.status = "failed"
        record.error = last_error or "Unknown error"
        self.logger.error(f"Tool {tool_def.id} failed after {self.max_retries} attempts")
        
        return record
    
    async def _invoke_tool(
        self,
        tool_def: ToolDefinition,
        arguments: dict[str, Any]
    ) -> Any:
        """
        Invoke a tool through its MCP server.
        
        This method should be overridden or injected with actual MCP server
        invocation logic. Currently returns a placeholder for testing.
        
        Args:
            tool_def: Tool definition.
            arguments: Tool input arguments.
            
        Returns:
            Tool result/output.
        """
        # TODO: Implement actual tool invocation via MCP server (e.g., langchain_mcp ClientSession)
        # For now, return a placeholder that can be overridden in tests
        return {
            "status": "success",
            "message": f"Tool {tool_def.name} invoked with {len(arguments)} arguments"
        }
    
    async def _exponential_backoff(self, attempt_number: int) -> None:
        """
        Apply exponential backoff with jitter between retries.
        
        Formula: base_delay = 2^(attempt_number - 1) seconds
        Jitter: uniform random ±0-500ms
        Cap: 10 seconds maximum
        
        Args:
            attempt_number: Current attempt number (1-indexed).
        """
        # Exponential backoff: 2^(attempt-1) -> 1s, 2s, 4s, 8s, ...
        base_delay_ms = (2 ** (attempt_number - 1)) * 1000
        
        # Add jitter: uniform random between 0 and 500ms
        jitter_ms = random.uniform(0, 500)
        
        # Total backoff, capped at 10 seconds
        backoff_ms = min(base_delay_ms + jitter_ms, 10000)
        
        self.logger.debug(f"Backoff for {backoff_ms:.0f}ms before retry (attempt {attempt_number})")
        await asyncio.sleep(backoff_ms / 1000.0)
