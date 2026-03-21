import os
import json
from typing import List, Dict, Any
from openai import AsyncAzureOpenAI
from .llm_provider import LLMProvider, Message, LLMResponse, ToolCall

class AzureOpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, azure_endpoint: str, api_version: str, deployment_name: str, temperature: float = 0.7):
        self.client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint
        )
        self.deployment_name = deployment_name
        self.temperature = temperature

    async def generate(self, history: List[Message], tools: List[Dict[str, Any]]) -> LLMResponse:
        # Convert messages to OpenAI format
        openai_messages = []
        for msg in history:
            message_dict = {"role": msg.role}
            if msg.content is not None:
                message_dict["content"] = msg.content
            elif msg.role == "assistant" and msg.tool_calls:
                # Ensure content is not null for strict APIs
                message_dict["content"] = ""
            
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
            model=self.deployment_name,
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
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            } if response.usage else None
        )
