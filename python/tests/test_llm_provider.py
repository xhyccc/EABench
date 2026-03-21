"""Tests for src.core.llm_provider (MockLLMProvider and data models)."""

import asyncio
import pytest

from src.core.llm_provider import (
    LLMProvider,
    LLMResponse,
    Message,
    ToolCall,
    MockLLMProvider,
)


class TestDataModels:
    def test_message_with_role_and_content(self):
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_calls is None

    def test_message_with_tool_calls(self):
        call = ToolCall(id="tc1", name="read_file", arguments={"path": "file.txt"})
        msg = Message(role="assistant", tool_calls=[call])
        assert msg.tool_calls[0].name == "read_file"

    def test_llm_response_content_only(self):
        resp = LLMResponse(content="The answer is 42.")
        assert resp.content == "The answer is 42."
        assert resp.tool_calls is None
        assert resp.usage is None

    def test_llm_response_with_tool_calls(self):
        call = ToolCall(id="c1", name="list_files", arguments={"path": "."})
        resp = LLMResponse(tool_calls=[call])
        assert resp.tool_calls[0].name == "list_files"

    def test_llm_response_with_usage(self):
        resp = LLMResponse(content="hi", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        assert resp.usage["total_tokens"] == 15

    def test_tool_call_fields(self):
        call = ToolCall(id="x", name="execute_command", arguments={"command": "ls"})
        assert call.id == "x"
        assert call.arguments["command"] == "ls"


class TestMockLLMProvider:
    def test_returns_mock_response(self):
        provider = MockLLMProvider()
        history = [Message(role="user", content="What is the weather?")]
        response = asyncio.run(provider.generate(history, tools=[]))
        assert isinstance(response, LLMResponse)
        assert response.content is not None or response.tool_calls is not None

    def test_list_files_trigger(self):
        """MockLLMProvider calls list_files tool when 'list files' is in user message."""
        provider = MockLLMProvider()
        history = [Message(role="user", content="Please list files in the directory")]
        response = asyncio.run(provider.generate(history, tools=[]))
        assert response.tool_calls is not None
        assert response.tool_calls[0].name == "list_files"

    def test_tool_result_returns_content(self):
        """When last message is a tool result, mock returns a final content response."""
        provider = MockLLMProvider()
        history = [
            Message(role="user", content="list files"),
            Message(role="tool", tool_call_id="tc1", content="file1.txt\nfile2.txt"),
        ]
        response = asyncio.run(provider.generate(history, tools=[]))
        assert response.content is not None
        assert "file1.txt" in response.content or "result" in response.content.lower()

    def test_get_completion_returns_string(self):
        provider = MockLLMProvider()
        messages = [{"role": "user", "content": "Hello"}]
        result = asyncio.run(provider.get_completion(messages))
        assert isinstance(result, str)
