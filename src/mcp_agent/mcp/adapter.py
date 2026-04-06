"""
Tool adapter for LangChain integration.

Converts ToolDefinition objects to LangChain-compatible Tool format for use
with LLM decision-making and invocation.
"""

from langchain_core.tools import Tool, StructuredTool
from pydantic import BaseModel, create_model

from mcp_agent.mcp.registry import ToolDefinition


class MCPToolAdapter:
    """
    Converts MCP tool definitions to LangChain Tool objects.
    
    Bridges the gap between MCP tool metadata and LangChain's tool interface,
    enabling the LLM to reason about tool availability and make invocation decisions.
    """
    
    @staticmethod
    def to_langchain_tool(tool_def: ToolDefinition) -> Tool:
        """
        Convert a ToolDefinition to a LangChain Tool object.
        
        Args:
            tool_def: The MCP tool definition to convert.
            
        Returns:
            A LangChain Tool object with schema and description.
        """
        # Create a Pydantic model from the input schema for argument validation
        schema = tool_def.input_schema
        
        # Build dynamic Pydantic model from JSON schema
        fields = {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        for prop_name, prop_schema in properties.items():
            # Determine field type from JSON schema
            field_type = MCPToolAdapter._json_type_to_python(
                prop_schema.get("type", "string")
            )
            
            # Set default or make required
            if prop_name in required:
                fields[prop_name] = (field_type, ...)  # ... means required
            else:
                default = prop_schema.get("default")
                fields[prop_name] = (field_type, default)
        
        # Create the Pydantic model
        try:
            if fields:
                args_schema = create_model(
                    f"{tool_def.name}_input",
                    **fields
                )
            else:
                # Empty schema - create model with no fields
                args_schema = BaseModel
        except Exception:
            # Fallback to BaseModel if schema generation fails
            args_schema = BaseModel
        
        # Create a dummy function that returns the schema
        # The actual execution will be handled by the agent's node_invoke_tool
        def _tool_placeholder(*args, **kwargs):
            """Placeholder function - actual execution handled by agent."""
            return f"Tool {tool_def.name} called (execution handled by agent)"
        
        # Create LangChain StructuredTool
        tool = StructuredTool(
            name=tool_def.name,
            description=tool_def.description or f"Tool: {tool_def.name}",
            func=_tool_placeholder,
            args_schema=args_schema if hasattr(args_schema, "model_fields") else None,
        )
        
        # Attach tool definition metadata for later reference
        tool.metadata = {
            "tool_id": tool_def.id,
            "server_name": tool_def.server_name,
            "timeout_ms": tool_def.timeout_ms,
            "fallback_tool_id": tool_def.fallback_tool_id,
        }
        
        return tool
    
    @staticmethod
    def _json_type_to_python(json_type: str):
        """
        Convert JSON schema type to Python type.
        
        Args:
            json_type: JSON schema type string.
            
        Returns:
            Corresponding Python type.
        """
        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        return type_mapping.get(json_type, str)
    
    @staticmethod
    def create_tool_list_from_registry(registry) -> list[Tool]:
        """
        Create LangChain Tool objects for all tools in a registry.
        
        Args:
            registry: ToolRegistry instance to convert.
            
        Returns:
            List of LangChain Tool objects ready for LLM use.
        """
        tools = []
        for tool_def in registry.list_all():
            try:
                tool = MCPToolAdapter.to_langchain_tool(tool_def)
                tools.append(tool)
            except Exception as e:
                # Log and skip problematic tools
                pass
        return tools
