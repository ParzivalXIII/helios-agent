"""
MCP server discovery and tool aggregation.

Connects to configured MCP servers (stdio, sse, fastmcp), discovers available tools,
and populates the ToolRegistry at application startup.
"""

import importlib
import json
from pathlib import Path
from typing import Any

from loguru import logger

from mcp_agent.mcp.registry import ToolDefinition, ToolRegistry
from mcp_agent.settings import Settings


class MCPAggregator:
    """
    Discovers and aggregates tools from all configured MCP servers.
    
    Supports multiple transport types:
    - stdio: Subprocess-based MCP server communication
    - sse: Server-Sent Events over HTTP
    - fastmcp: In-process FastMCP server instance
    """
    
    def __init__(self, settings: Settings) -> None:
        """
        Initialize the aggregator.
        
        Args:
            settings: Application settings containing MCP configuration path.
        """
        self.settings = settings
        self.config_path = Path(settings.mcp_config_path)
        self.logger = logger.bind(component="MCPAggregator")
    
    async def discover_all(self) -> ToolRegistry:
        """
        Discover tools from all configured MCP servers.
        
        Reads the MCP configuration file, connects to each server using the
        appropriate transport, retrieves available tools, and normalizes them
        into ToolDefinition objects.
        
        Returns:
            ToolRegistry populated with all discovered tools.
            
        Raises:
            FileNotFoundError: If MCP configuration file not found.
            ValueError: If configuration is invalid or no servers can be reached.
        """
        registry = ToolRegistry()
        
        if not self.config_path.exists():
            self.logger.error(f"MCP config not found at {self.config_path}")
            raise FileNotFoundError(f"MCP config file not found: {self.config_path}")
        
        # Parse YAML configuration
        try:
            import yaml
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
        except ImportError:
            self.logger.error("PyYAML not available")
            raise ImportError("PyYAML required for MCP configuration parsing")
        except Exception as e:
            self.logger.error(f"Failed to parse MCP config: {e}")
            raise ValueError(f"Invalid MCP config: {e}")
        
        servers = config.get("servers", [])
        if not servers:
            self.logger.warning("No MCP servers configured")
            return registry
        
        # Process each server
        for server_config in servers:
            try:
                server_name = server_config.get("name")
                server_type = server_config.get("type")
                
                self.logger.info(f"Discovering tools from server: {server_name} ({server_type})")
                
                tools = await self._discover_server_tools(server_name, server_type, server_config)
                
                # Register tools from this server
                for tool_data in tools:
                    tool_def = self._normalize_tool(tool_data, server_name)
                    try:
                        registry.register(tool_def)
                        self.logger.debug(f"Registered tool: {tool_def.id} from {server_name}")
                    except ValueError as e:
                        self.logger.warning(f"Duplicate tool skipped: {e}")
                
                self.logger.info(f"Server {server_name}: discovered {len(tools)} tools")
                
            except Exception as e:
                self.logger.error(f"Error discovering tools from {server_config.get('name')}: {e}")
                # Continue with next server instead of failing completely
                continue
        
        total_tools = registry.count()
        self.logger.info(f"MCP discovery complete: {total_tools} tools registered from {len(servers)} servers")
        
        return registry
    
    async def _discover_server_tools(
        self,
        server_name: str,
        server_type: str,
        server_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Discover tools from a specific MCP server based on transport type.
        
        Args:
            server_name: Friendly name of the server.
            server_type: Transport type ("stdio", "sse", or "fastmcp").
            server_config: Server configuration dictionary.
            
        Returns:
            List of tool definitions from the server.
        """
        if server_type == "fastmcp":
            return await self._discover_fastmcp_tools(server_name, server_config)
        elif server_type == "stdio":
            return await self._discover_stdio_tools(server_name, server_config)
        elif server_type == "sse":
            return await self._discover_sse_tools(server_name, server_config)
        else:
            self.logger.warning(f"Unknown server type: {server_type}")
            return []
    
    async def _discover_fastmcp_tools(
        self,
        server_name: str,
        server_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Discover tools from an in-process FastMCP server.
        
        Args:
            server_name: Server name.
            server_config: Configuration with "module_path" key.
            
        Returns:
            List of tool definitions.
        """
        try:
            module_path = server_config.get("module_path")
            if not module_path:
                self.logger.warning(f"FastMCP server {server_name} missing module_path")
                return []
            
            # Import the FastMCP server module
            module_name, class_name = module_path.rsplit(".", 1) if "." in module_path else (module_path, None)
            
            # Try to import as module first
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError:
                # Try parent module
                parent_module_name = ".".join(module_name.split(".")[:-1])
                module = importlib.import_module(parent_module_name)
            
            # For FastMCP, we look for a server instance or function that returns tools
            # This is a simplified implementation - actual FastMCP integration depends on
            # how the server is structured
            tools = []
            
            # Look for a list_tools attribute or method
            if hasattr(module, "list_tools"):
                tools_func = getattr(module, "list_tools")
                if callable(tools_func):
                    tools = await tools_func() if hasattr(tools_func, "__await__") else tools_func()
                else:
                    tools = tools_func
            
            # If not found, try to instantiate a server
            elif hasattr(module, "server"):
                server_instance = getattr(module, "server")
                if hasattr(server_instance, "list_tools"):
                    tools_func = getattr(server_instance, "list_tools")
                    if callable(tools_func):
                        tools = await tools_func() if hasattr(tools_func, "__await__") else tools_func()
                    else:
                        tools = tools_func
            
            return tools if isinstance(tools, list) else []
            
        except Exception as e:
            self.logger.error(f"FastMCP discovery failed for {server_name}: {e}")
            return []
    
    async def _discover_stdio_tools(
        self,
        server_name: str,
        server_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Discover tools from a stdio-based MCP server.
        
        Args:
            server_name: Server name.
            server_config: Configuration with "command" and "args" keys.
            
        Returns:
            List of tool definitions.
        """
        try:
            # langchain-mcp provides StdioClientSession for stdio transport
            from langchain_mcp import ClientSession
            
            command = server_config.get("command")
            args = server_config.get("args", [])
            
            if not command:
                self.logger.warning(f"Stdio server {server_name} missing command")
                return []
            
            # Construct full command
            full_cmd = [command] + args if isinstance(args, list) else [command, args]
            
            # Create a stdio client session
            async with ClientSession.stdio_session(
                program=full_cmd[0],
                args=full_cmd[1:],
                timeout=self.settings.tool_timeout_ms / 1000.0
            ) as session:
                # Get list of tools from the server
                tools_response = await session.call_tool("list_tools", {})
                
                if isinstance(tools_response, dict) and "tools" in tools_response:
                    return tools_response["tools"]
                return []
                
        except Exception as e:
            self.logger.error(f"Stdio discovery failed for {server_name}: {e}")
            return []
    
    async def _discover_sse_tools(
        self,
        server_name: str,
        server_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Discover tools from an SSE-based MCP server over HTTP.
        
        Args:
            server_name: Server name.
            server_config: Configuration with "url" key.
            
        Returns:
            List of tool definitions.
        """
        try:
            from langchain_mcp import ClientSession
            import httpx
            
            url = server_config.get("url")
            if not url:
                self.logger.warning(f"SSE server {server_name} missing url")
                return []
            
            # Create SSE client session
            async with ClientSession.sse_session(
                url,
                timeout=self.settings.tool_timeout_ms / 1000.0
            ) as session:
                # Get list of tools from the server
                tools_response = await session.call_tool("list_tools", {})
                
                if isinstance(tools_response, dict) and "tools" in tools_response:
                    return tools_response["tools"]
                return []
                
        except Exception as e:
            self.logger.error(f"SSE discovery failed for {server_name}: {e}")
            return []
    
    def _normalize_tool(self, tool_data: dict[str, Any], server_name: str) -> ToolDefinition:
        """
        Normalize tool data from MCP server into a ToolDefinition.
        
        Args:
            tool_data: Raw tool data from the MCP server.
            server_name: Name of the providing server.
            
        Returns:
            Normalized ToolDefinition object.
        """
        # Extract tool metadata
        tool_name = tool_data.get("name", "unknown_tool")
        tool_id = f"{server_name}.{tool_name}"
        
        # Safely extract schemas with defaults
        input_schema = tool_data.get("inputSchema", {})
        output_schema = tool_data.get("outputSchema", {})
        
        # Create ToolDefinition
        return ToolDefinition(
            id=tool_id,
            name=tool_name,
            server_name=server_name,
            description=tool_data.get("description", f"{tool_name} tool from {server_name}"),
            input_schema=input_schema if isinstance(input_schema, dict) else {},
            output_schema=output_schema if isinstance(output_schema, dict) else {},
            timeout_ms=tool_data.get("timeout_ms", self.settings.tool_timeout_ms),
            fallback_tool_id=tool_data.get("fallback_tool_id")
        )
