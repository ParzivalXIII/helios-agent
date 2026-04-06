"""
Agent graph nodes.

Implements the graph nodes (think, decide_action, invoke_tool, tool_result,
evaluate_result, direct_response, error, respond) for the LangGraph agent.
"""

import logging
from typing import Any

from mcp_agent.agent.state import AgentState, Message
from mcp_agent.settings import Settings
from mcp_agent.llm import LlmClient, LLMProviderError

logger = logging.getLogger(__name__)


# ============================================================================
# Graph node implementations
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
        return state
    
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
    
    return state


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
    
    return state


async def node_invoke_tool(state: AgentState, executor: Any = None) -> dict:
    """
    Tool invocation node: executes the selected tool.
    
    Process:
    1. Resolve state.selected_tool_id from the tool registry
    2. Execute tool via ToolExecutor with timeout and retry support
    3. Append ToolCallRecord to state.tool_calls_this_turn
    4. Store result in state.current_tool_output
    5. Route to node_tool_result
    
    Args:
        state: Current agent state.
        executor: ToolExecutor instance (injected from context).
        
    Returns:
        Updated state dictionary with tool execution record.
    """
    if not executor or not state.selected_tool_id:
        logger.error("node_invoke_tool: Missing executor or selected_tool_id")
        state.current_tool_output = None
        state.last_error = "Tool execution failed: executor not available"
        return {"state": state}
    
    try:
        # Execute the tool with retry and fallback support
        tool_record = await executor.execute(
            state.selected_tool_id,
            state.metadata.get("tool_arguments", {})
        )
        
        # Append to tool call history
        state.tool_calls_this_turn.append(tool_record)
        
        # Store output for next node
        state.current_tool_output = tool_record.output if tool_record.status == "success" else None
        
        if tool_record.status != "success":
            state.last_error = tool_record.error or "Tool execution failed"
            state.error_count += 1
        
        logger.info(f"Tool executed: {state.selected_tool_id}, status={tool_record.status}")
        
    except Exception as e:
        logger.error(f"Tool invocation error: {e}")
        state.last_error = str(e)
        state.error_count += 1
        state.current_tool_output = None
    
    return {"state": state}


async def node_tool_result(state: AgentState) -> dict:
    """
    Tool result node: processes tool output and prepares for evaluation.
    
    Process:
    1. Append tool output as a "tool" message to conversation history
    2. Store raw output in state.current_tool_output for next node
    3. Update turn metadata with tool call summary
    
    Args:
        state: Current agent state with tool execution result.
        
    Returns:
        Updated state dictionary with tool output added to history.
    """
    try:
        # Add tool result to conversation history
        if state.current_tool_output is not None:
            # Get the most recent tool call
            if state.tool_calls_this_turn:
                last_tool = state.tool_calls_this_turn[-1]
                tool_message = Message(
                    role="tool",
                    content=str(state.current_tool_output),
                    created_at=state.last_activity
                )
                state.messages.append(tool_message)
                logger.debug(f"Tool result added to conversation: {last_tool.tool_id}")
        
        # If tool call failed, prepare error context
        elif state.last_error:
            error_message = Message(
                role="tool",
                content=f"Error: {state.last_error}",
                created_at=state.last_activity
            )
            state.messages.append(error_message)
            logger.warning(f"Tool error recorded in conversation: {state.last_error}")
    
    except Exception as e:
        logger.error(f"Error in node_tool_result: {e}")
        state.last_error = str(e)
    
    return {"state": state}


async def node_evaluate_result(state: AgentState, llm_client: LlmClient) -> dict:
    """
    Result evaluation node: synthesizes final answer from tool output.
    
    Process:
    1. Call LLMClient.complete() with full conversation history including tool output
    2. Generate synthesized answer grounding the response in the tool output
    3. Store answer in state for final response packaging
    
    Args:
        state: Current agent state with tool output in conversation history.
        llm_client: LLM client for generating the synthesis response.
        
    Returns:
        Updated state dictionary with final synthesized answer.
    """
    try:
        # Build message context including tool output
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in state.messages[-10:]  # Use last 10 messages for context
        ]
        
        # Add instruction to synthesize answer from tool output
        synthesis_prompt = {
            "role": "user",
            "content": "Based on the tool output above, provide a clear and helpful answer to the original question."
        }
        messages.append(synthesis_prompt)
        
        logger.debug(f"Evaluating tool result for turn {state.turn_count}")
        
        # Get LLM synthesis
        synthesis = await llm_client.complete(messages)
        
        state.current_thought = synthesis
        
        logger.info(f"Tool result evaluated, synthesis generated for turn {state.turn_count}")
        
    except LLMProviderError as e:
        logger.error(f"LLM error in evaluate_result: {e}")
        state.last_error = f"Failed to evaluate tool result: {e.detail}"
        state.error_count += 1
        state.current_thought = ""
    except Exception as e:
        logger.error(f"Unexpected error in node_evaluate_result: {e}")
        state.last_error = str(e)
        state.error_count += 1
    
    return {"state": state}


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
    
    return state


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
    
    return state


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
    
    return state
