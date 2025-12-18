import os
import json
from typing import List, Dict, Any
from openai import AsyncOpenAI
from .llm_provider import LLMProvider, Message, LLMResponse, ToolCall

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str, temperature: float = 0.7):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.temperature = temperature

    async def generate(self, history: List[Message], tools: List[Dict[str, Any]]) -> LLMResponse:
        # Convert messages to OpenAI format
        openai_messages = []
        for msg in history:
            message_dict = {"role": msg.role}
            if msg.content:
                message_dict["content"] = msg.content
            
            if msg.tool_calls:
                openai_tool_calls = []
                for tc in msg.tool_calls:
                    openai_tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    })
                message_dict["tool_calls"] = openai_tool_calls
            
            if msg.tool_call_id:
                message_dict["tool_call_id"] = msg.tool_call_id
            
            openai_messages.append(message_dict)

        # Prepare tools if available
        openai_tools = tools if tools else None

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            tools=openai_tools,
            temperature=self.temperature
        )

        choice = response.choices[0]
        message = choice.message

        tool_calls = None
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments)
                ))

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls
        )
