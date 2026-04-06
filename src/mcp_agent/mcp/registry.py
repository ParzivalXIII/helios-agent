"""
Tool registry and definitions for MCP server integration.

Provides the ToolDefinition dataclass and ToolRegistry class for managing
tool catalogs discovered from MCP servers at application startup.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    """
    Complete definition of a tool provided by an MCP server.
    
    Attributes:
        id: Globally unique tool identifier (format: "server_name.tool_name").
        name: Tool's display name as declared by the MCP server.
        server_name: Name of the MCP server providing this tool.
        description: Human-readable description of tool functionality.
        input_schema: JSON Schema describing expected input parameters.
        output_schema: JSON Schema describing expected output format.
        timeout_ms: Maximum execution time in milliseconds before timeout.
        fallback_tool_id: Optional ID of a fallback tool to use if this tool fails.
    """
    
    id: str
    name: str
    server_name: str
    description: str
    input_schema: dict
    output_schema: dict
    timeout_ms: int
    fallback_tool_id: str | None = None


class ToolRegistry:
    """
    Thread-safe registry for managing tool definitions.
    
    Maintains a catalog of all tools discovered from configured MCP servers.
    Populated once at application startup and remains immutable during process lifetime.
    """
    
    def __init__(self) -> None:
        """Initialize an empty tool registry."""
        self._tools: dict[str, ToolDefinition] = {}
    
    def register(self, tool: ToolDefinition) -> None:
        """
        Register a new tool in the registry.
        
        Args:
            tool: ToolDefinition to register.
            
        Raises:
            ValueError: If a tool with the same ID already exists.
        """
        if tool.id in self._tools:
            raise ValueError(f"Tool with ID '{tool.id}' already registered")
        self._tools[tool.id] = tool
    
    def get(self, tool_id: str) -> ToolDefinition | None:
        """
        Retrieve a tool by its ID.
        
        Args:
            tool_id: The tool's unique identifier.
            
        Returns:
            ToolDefinition if found, None otherwise.
        """
        return self._tools.get(tool_id)
    
    def list_all(self) -> list[ToolDefinition]:
        """
        Retrieve all registered tools.
        
        Returns:
            List of all ToolDefinition objects in the registry.
        """
        return list(self._tools.values())
    
    def count(self) -> int:
        """
        Get the total number of registered tools.
        
        Returns:
            Number of tools in the registry.
        """
        return len(self._tools)
