from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any]

class Message(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None # For tool results

class LLMResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, history: List[Message], tools: List[Dict[str, Any]]) -> LLMResponse:
        pass

    async def get_completion(self, messages: List[Dict[str, str]]) -> str:
        """Simple completion for evaluation tasks."""
        # Default implementation wraps generate
        history = [Message(role=m["role"], content=m["content"]) for m in messages]
        response = await self.generate(history, [])
        return response.content or ""

class MockLLMProvider(LLMProvider):
    """A mock provider for testing."""
    async def generate(self, history: List[Message], tools: List[Dict[str, Any]]) -> LLMResponse:
        last_msg = history[-1]
        
        # If the last message was a tool result, return a final answer summarizing it
        if last_msg.role == "tool":
            return LLMResponse(content=f"I have executed the tool. The result was: {last_msg.content}")

        # Simple mock logic: if the last message is user "list files", call list_files tool
        if last_msg.role == "user" and "list files" in last_msg.content.lower():
             return LLMResponse(
                 tool_calls=[ToolCall(id="call_1", name="list_files", arguments={"path": "."})]
             )
        
        return LLMResponse(content="I am a mock agent.")
