"""
Agent graph nodes and LLM client.

Implements the graph nodes (think, decide_action, invoke_tool, tool_result,
evaluate_result, direct_response, error, respond) and the LlmClient for
communicating with the LLM provider.
"""

import httpx
import logging
from typing import Any

from mcp_agent.agent.state import AgentState, Message
from mcp_agent.settings import Settings

logger = logging.getLogger(__name__)


# Custom exceptions
class LLMProviderError(Exception):
    """Raised when LLM provider returns a non-200 HTTP response."""
    pass


class LlmClient:
    """
    Async HTTP client for communicating with the LLM provider.
    
    Wraps httpx.AsyncClient to provide a simple interface for completing
    conversations via the LLM provider's API.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize the LLM client.
        
        Args:
            settings: Settings instance with llm_base_url and llm_model
        """
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            timeout=30.0,  # 30 second timeout for LLM calls
        )
    
    async def complete(self, messages: list[dict]) -> str:
        """
        Request a completion from the LLM provider.
        
        Sends a list of messages to the LLM provider and returns the
        generated response text. Uses the model specified in settings.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
                     Format: [{"role": "user"|"assistant", "content": "..."}]
            
        Returns:
            The assistant's response text
            
        Raises:
            LLMProviderError: If the provider returns non-200 HTTP status
            httpx.TimeoutException: If the request times out
            httpx.RequestError: If the request fails for other reasons
        """
        try:
            # Prepare the request payload
            payload = {
                "model": self.settings.llm_model,
                "messages": messages,
            }
            
            # Make the request to /chat/completions endpoint
            response = await self.client.post(
                "/chat/completions",
                json=payload,
            )
            
            # Check for errors
            if response.status_code != 200:
                error_detail = {
                    "provider": "openrouter",  # Default provider name
                    "http_status": response.status_code,
                    "response_text": response.text[:500],  # First 500 chars
                }
                logger.error(
                    f"LLM provider returned {response.status_code}: {response.text[:200]}"
                )
                raise LLMProviderError(
                    f"LLM provider returned {response.status_code}",
                    error_detail,
                )
            
            # Parse the response
            data = response.json()
            
            # Extract the assistant's message
            # Assumes OpenAI-compatible response format:
            # {"choices": [{"message": {"content": "..."}}]}
            if "choices" not in data or not data["choices"]:
                raise LLMProviderError(
                    "Invalid LLM response format: missing choices",
                    {"response": data},
                )
            
            content = data["choices"][0].get("message", {}).get("content", "")
            if not content:
                raise LLMProviderError(
                    "Invalid LLM response format: missing content",
                    {"response": data},
                )
            
            logger.debug(f"LLM responded with {len(content)} characters")
            return content
        
        except httpx.TimeoutException as e:
            logger.error(f"LLM provider request timed out: {e}")
            raise LLMProviderError(
                "LLM provider request timed out",
                {"error": str(e)},
            )
        except httpx.RequestError as e:
            logger.error(f"LLM provider request failed: {e}")
            raise LLMProviderError(
                "LLM provider request failed",
                {"error": str(e)},
            )
    
    async def aclose(self) -> None:
        """Close the HTTP client connection."""
        await self.client.aclose()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.aclose()


# ============================================================================
# Graph node implementations will go here in subsequent tasks
# ============================================================================

async def node_think(state: AgentState, llm_client: LlmClient, settings: Settings) -> dict:
    """
    Reasoning node: calls LLM to generate chain-of-thought.
    
    Process:
    1. Check if turn_count >= max_turns; if so, route to error
    2. Increment turn_count
    3. Build context window from last 5 messages
    4. Call LlmClient.complete() to get LLM reasoning
    5. Store reasoning in state.current_thought
    
    Args:
        state: Current agent state
        llm_client: LlmClient instance for LLM calls
        settings: Settings instance for max_turns config
        
    Returns:
        Updated state dict
        
    Raises:
        LLMProviderError: If LLM provider fails
    """
    # Check turn limit BEFORE incrementing
    if state.turn_count >= settings.max_turns:
        logger.warning(
            f"Session {state.session_id} has reached max_turns ({state.turn_count}/{settings.max_turns})"
        )
        state.current_decision = "error"
        state.last_error = f"Maximum turns ({settings.max_turns}) exceeded"
        return {"state": state}
    
    # Increment turn count
    state.turn_count += 1
    logger.info(f"Session {state.session_id} turn {state.turn_count} started")
    
    # Build context window: last 5 messages in the conversation
    context_messages = []
    
    # Add system prompt
    system_prompt = "You are a helpful assistant. Reason through the user's request step by step."
    context_messages.append({
        "role": "system",
        "content": system_prompt,
    })
    
    # Add conversation history (last 5 messages)
    recent_messages = state.messages[-5:] if state.messages else []
    for msg in recent_messages:
        context_messages.append({
            "role": msg.role,
            "content": msg.content,
        })
    
    # Add current input as user message
    if state.current_input:
        context_messages.append({
            "role": "user",
            "content": state.current_input,
        })
    
    # Call LLM to get reasoning
    try:
        thought = await llm_client.complete(context_messages)
        state.current_thought = thought
        logger.debug(
            f"Session {state.session_id} LLM thought: {thought[:100]}..."
        )
    except LLMProviderError as e:
        logger.error(f"LLM provider error: {e}")
        state.current_decision = "error"
        state.last_error = f"LLM provider error: {str(e)}"
        state.error_count += 1
        raise
    
    return {"state": state}


async def node_decide_action(state: AgentState) -> dict:
    """
    Decision node: parses LLM output to determine next action.
    
    Process:
    1. Analyze state.current_thought from node_think
    2. Determine AgentDecision: "use_tool" | "direct_response" | "error"
    3. If "use_tool", parse tool ID from LLM output and set state.selected_tool_id
    4. If "direct_response", no tool invocation needed
    5. Set state.current_decision
    
    For now (US1), we always route to "direct_response" since no tools are available.
    In Phase 4, this will be enhanced to parse tool selections from the LLM output.
    
    Args:
        state: Current agent state
        
    Returns:
        Updated state dict
    """
    # For US1 (multi-turn chat without tools), always use direct_response
    # In Phase 4 (US2), this will parse the LLM thought to decide tool use
    
    if not state.available_tools or len(state.available_tools) == 0:
        # No tools available; always direct response
        state.current_decision = "direct_response"
        logger.debug(
            f"Session {state.session_id} routing to direct_response (no tools available)"
        )
    else:
        # Tools available; for now still route to direct_response
        # This will be enhanced in Phase 4 to parse tool selection from LLM output
        state.current_decision = "direct_response"
        logger.debug(
            f"Session {state.session_id} routing to direct_response"
        )
    
    return {"state": state}


async def node_invoke_tool(state: AgentState) -> dict:
    """
    Tool invocation node: executes the selected tool.
    
    This is a placeholder that will be implemented in Phase 4 (T028).
    """
    raise NotImplementedError("node_invoke_tool will be implemented in Phase 4")


async def node_tool_result(state: AgentState) -> dict:
    """
    Tool result node: processes tool output.
    
    This is a placeholder that will be implemented in Phase 4 (T028).
    """
    raise NotImplementedError("node_tool_result will be implemented in Phase 4")


async def node_evaluate_result(state: AgentState) -> dict:
    """
    Result evaluation node: synthesizes answer from tool output.
    
    This is a placeholder that will be implemented in Phase 4 (T028).
    """
    raise NotImplementedError("node_evaluate_result will be implemented in Phase 4")


async def node_direct_response(state: AgentState, llm_client: LlmClient) -> dict:
    """
    Direct response node: generates LLM response without tools.
    
    Called when node_decide_action determines no tool use is needed.
    Calls LlmClient to generate a final response based on conversation context.
    
    Args:
        state: Current agent state
        llm_client: LlmClient instance for LLM calls
        
    Returns:
        Updated state dict
    """
    # Build context for final response
    context_messages = []
    
    # Add system prompt
    system_prompt = "You are a helpful assistant. Provide a clear, concise answer to the user's request."
    context_messages.append({
        "role": "system",
        "content": system_prompt,
    })
    
    # Add recent messages (last 5)
    recent_messages = state.messages[-5:] if state.messages else []
    for msg in recent_messages:
        context_messages.append({
            "role": msg.role,
            "content": msg.content,
        })
    
    # Add current input
    if state.current_input:
        context_messages.append({
            "role": "user",
            "content": state.current_input,
        })
    
    # Get final response from LLM
    try:
        response = await llm_client.complete(context_messages)
        logger.debug(
            f"Session {state.session_id} generated direct response: {response[:100]}..."
        )
        # Store response as the final answer
        # Note: This will be added to state.messages in node_respond
        state.current_thought = response  # Temporarily store in current_thought
    except LLMProviderError as e:
        logger.error(f"LLM provider error in direct_response: {e}")
        state.current_decision = "error"
        state.last_error = f"Failed to generate response: {str(e)}"
        state.error_count += 1
        raise
    
    return {"state": state}


async def node_error(state: AgentState) -> dict:
    """
    Error node: constructs error response state.
    
    Called when an error occurs that cannot be recovered from.
    Updates state with error information for the final response.
    
    Args:
        state: Current agent state
        
    Returns:
        Updated state dict
    """
    # Ensure last_error is set
    if not state.last_error:
        state.last_error = "An unexpected error occurred"
    
    state.error_count += 1
    logger.warning(
        f"Session {state.session_id} error: {state.last_error} (count: {state.error_count})"
    )
    
    return {"state": state}


async def node_respond(state: AgentState) -> dict:
    """
    Response node: packages state into final response for the client.
    
    Process:
    1. If state.current_decision == "error", return error envelope
    2. Otherwise, extract the response from state.current_thought
    3. Create final Message and append to state.messages
    4. Update state.last_activity timestamp
    5. Package response for the API layer
    
    Args:
        state: Current agent state with final decision
        
    Returns:
        Updated state dict with final response packaged
    """
    from datetime import datetime, timezone
    
    # Determine the response content
    if state.current_decision == "error":
        # Error case; response will be error message
        response_content = state.last_error or "An unknown error occurred"
    else:
        # Success case; use current_thought (which was set by node_direct_response)
        response_content = state.current_thought or "No response generated"
    
    # Add the response as an assistant message to the conversation
    response_message = Message(
        role="assistant",
        content=response_content,
        created_at=datetime.now(timezone.utc),
    )
    state.messages.append(response_message)
    
    # Update last activity
    state.last_activity = datetime.now(timezone.utc)
    
    logger.info(
        f"Session {state.session_id} turn {state.turn_count} completed. "
        f"Decision: {state.current_decision}, "
        f"Messages: {len(state.messages)}"
    )
    
    return {"state": state}
