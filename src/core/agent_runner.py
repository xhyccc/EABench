import asyncio
from typing import List, Dict, Any
from pydantic import BaseModel
from .llm_provider import LLMProvider, Message, ToolCall
from .tool_registry import ToolRegistry
from ..config.agent_config import AgentConfig
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
        if not self.history:
            system_prompt = self.config.system_prompt
            
            # Inject User Profile if available
            if search_engine and search_engine.current_user_id:
                user = next((u for u in search_engine.tenant.users if u.id == search_engine.current_user_id), None)
                if user:
                    system_prompt += f"\n\nYou are acting on behalf of user: {user.profile.name.display_name} (ID: {user.id}).\n"
                    system_prompt += f"Your profile: {user.model_dump()}"

            self.history.append(Message(role="system", content=system_prompt))
        
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
        
        raise MaxTurnsExceededError()

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
