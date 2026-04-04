import asyncio
from typing import List, Dict, Any
from pydantic import BaseModel
from .llm_provider import LLMProvider, Message, ToolCall
from .tool_registry import ToolRegistry
from ..config.agent_config import AgentConfig, FlowStrategy
from ..sandbox.base import SandboxInterface
from .logger import debug_logger
from .query_analyzer import QueryAnalyzer

class MaxTurnsExceededError(Exception):
    pass

class AgentRunResult(BaseModel):
    response: str
    metrics: Dict[str, Any]

class AgentRunner:
    def __init__(self, agent_config: AgentConfig, llm_provider: LLMProvider, tool_registry: ToolRegistry):
        self.config = agent_config
        self.llm = llm_provider
        self.tools = tool_registry
        self.history: List[Message] = []
        self.query_analyzer = QueryAnalyzer(agent_config, llm_provider)

    async def run(self, user_query: str, sandbox: SandboxInterface, search_engine=None) -> AgentRunResult:
        # 1. Initialize Context (Only if history is empty)
        user_profile_str = ""  # Always defined so Researcher path can reference it safely
        if not self.history:
            system_prompt = self.config.system_prompt
            
            # Inject User Profile if available
            if search_engine and search_engine.current_user_id:
                user = next((u for u in search_engine.tenant.users if u.id == search_engine.current_user_id), None)
                if user:
                    user_profile_str = user.model_dump_json(indent=2)
                    if "{user_profile}" in system_prompt:
                        system_prompt = system_prompt.replace("{user_profile}", user_profile_str)
                    else:
                        # Fallback: Append if placeholder not found (backward compatibility)
                        system_prompt += f"\n\nYou are acting on behalf of user: {user.profile.name.display_name} (ID: {user.id}).\n"
                        system_prompt += f"Your profile: {user_profile_str}"

            self.history.append(Message(role="system", content=system_prompt))
        
        # Handle Researcher Strategy: Generate Plan First
        if self.config.flow.strategy == FlowStrategy.RESEARCHER:
            # Construct Planning Prompt
            planning_prompt_template = getattr(self.config, 'planning_prompt', None)
            if not planning_prompt_template:
                planning_prompt_template = (
                    "You are a research planner. Create a step-by-step plan to answer the user's request.\n"
                    "User Request: {user_query}\n"
                )
            
            # Fill placeholders
            planning_prompt = planning_prompt_template.replace("{user_query}", user_query)
            if "{user_profile}" in planning_prompt and user_profile_str:
                planning_prompt = planning_prompt.replace("{user_profile}", user_profile_str)

            # Generate Plan (using a temporary history to not pollute the main context yet, or maybe we want it?)
            # Let's keep it separate to ensure the planner focuses only on planning.
            planning_messages = [Message(role="user", content=planning_prompt)]
            
            debug_logger.log_llm_call([m.model_dump() for m in planning_messages])
            plan_response = await self.llm.generate(planning_messages, tools=[]) # No tools for planner
            debug_logger.log_llm_response(plan_response)
            
            plan = plan_response.content
            
            # Inject Plan into the conversation
            # We present the plan to the ReAct agent as the "User's Request" (or context for it)
            full_query = (
                f"Original Request: {user_query}\n\n"
                f"I have generated a research plan to address this:\n{plan}\n\n"
                f"Please execute this plan step-by-step to answer the original request."
            )
            self.history.append(Message(role="user", content=full_query))
        else:
            self.history.append(Message(role="user", content=user_query))

        metrics = {
            "tool_calls_count": 0,
            "llm_calls_count": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
        }

        # 2. Main ReAct Loop
        steps = 0
        while steps < self.config.flow.max_turns:
            # Generate Thought/Action
            # Get schemas for enabled tools
            enabled_tools = [
                s for s in self.tools.get_schemas() 
                if s["function"]["name"] in self.config.tools.definitions
            ]
            
            debug_logger.log_llm_call([m.model_dump() for m in self.history])
            response = await self.llm.generate(self.history, enabled_tools)
            debug_logger.log_llm_response(response)
            
            metrics["llm_calls_count"] += 1
            if response.usage:
                metrics["total_prompt_tokens"] += response.usage.get("prompt_tokens", 0)
                metrics["total_completion_tokens"] += response.usage.get("completion_tokens", 0)

            self.history.append(Message(role="assistant", content=response.content, tool_calls=response.tool_calls))

            if response.tool_calls:
                metrics["tool_calls_count"] += len(response.tool_calls)
                # Execute Tools in Sandbox
                for call in response.tool_calls:
                    debug_logger.log_tool_call(call.name, call.arguments)
                    result = await self._execute_tool(call, sandbox, search_engine)
                    debug_logger.log_tool_result(call.name, result)
                    self.history.append(Message(role="tool", tool_call_id=call.id, content=result))
            else:
                # Final Answer
                if metrics["llm_calls_count"] > 0:
                    metrics["avg_prompt_tokens"] = metrics["total_prompt_tokens"] / metrics["llm_calls_count"]
                    metrics["avg_completion_tokens"] = metrics["total_completion_tokens"] / metrics["llm_calls_count"]
                else:
                    metrics["avg_prompt_tokens"] = 0
                    metrics["avg_completion_tokens"] = 0
                
                return AgentRunResult(response=response.content, metrics=metrics)
            
            steps += 1
        
        raise MaxTurnsExceededError(
            f"Agent reached the maximum of {self.config.flow.max_turns} turns "
            "without producing a final answer."
        )

    async def _execute_tool(self, call: ToolCall, sandbox: SandboxInterface, search_engine=None) -> str:
        tool_func = self.tools.get_tool(call.name)
        if not tool_func:
            return f"Error: Tool {call.name} not found."
        
        try:
            import inspect
            sig = inspect.signature(tool_func)
            kwargs = call.arguments.copy()
            
            # Inject dependencies
            if "sandbox" in sig.parameters:
                kwargs["sandbox"] = sandbox
            if "search_engine" in sig.parameters:
                if search_engine is None:
                     return f"Error: Tool {call.name} requires search_engine but none provided."
                kwargs["search_engine"] = search_engine
            if "llm" in sig.parameters:
                kwargs["llm"] = self.llm
            if "query_analyzer" in sig.parameters:
                kwargs["query_analyzer"] = self.query_analyzer
                
            if asyncio.iscoroutinefunction(tool_func):
                return await tool_func(**kwargs)
            else:
                return tool_func(**kwargs)
        except Exception as e:
            return f"Error executing tool {call.name}: {str(e)}"
