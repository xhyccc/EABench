"""Pytest version of the original test_eval_parsing.py script.

Tests the YAML parsing helper and evaluation logic inside Evaluator.
"""

import asyncio
import pytest

from src.core.llm_provider import LLMProvider, LLMResponse, Message
from src.eval.evaluator import Evaluator


class MockJudgeLLM(LLMProvider):
    def __init__(self, response_content):
        self.response_content = response_content

    async def generate(self, history, tools):
        return LLMResponse(content=self.response_content)


class MockAssertion:
    description = "test"


def test_parse_yaml_response_score_and_explanation():
    """_parse_yaml_response correctly extracts a YAML block from LLM output."""
    yaml_str = """
    ```yaml
    score: 0.9
    explanation: "Good job."
    ```
    """
    mock_llm = MockJudgeLLM(yaml_str)
    evaluator = Evaluator(None, mock_llm, None, None)

    data = evaluator._parse_yaml_response(yaml_str)
    assert data["score"] == pytest.approx(0.9)
    assert data["explanation"] == "Good job."


def test_parse_yaml_response_assertions_block():
    """_parse_yaml_response correctly parses an assertions YAML block."""
    assertion_yaml = """
    ```yaml
    assertions:
      - id: 1
        passed: true
        reasoning: "Yes"
    final_score: 0.8
    summary: "Mostly passed."
    ```
    """
    mock_llm = MockJudgeLLM(assertion_yaml)
    evaluator = Evaluator(None, mock_llm, None, None)

    data = evaluator._parse_yaml_response(assertion_yaml)
    assert data["final_score"] == pytest.approx(0.8)
    assert data["summary"] == "Mostly passed."
    assert len(data["assertions"]) == 1
    assert data["assertions"][0]["passed"] is True


def test_citation_no_citations_in_response():
    """When the response contains no structured citations, score is 0.0."""
    mock_llm = MockJudgeLLM("")
    evaluator = Evaluator(None, mock_llm, None, None)

    score, explanation = asyncio.run(
        evaluator._evaluate_citation("query", [], "plain response with no citations")
    )
    assert score == pytest.approx(0.0)
    assert "No structured citations" in explanation


def test_assertion_evaluation_with_prompts():
    """_evaluate_assertions uses the assertion_check prompt and parses YAML response."""
    assertion_yaml = """
```yaml
assertions:
  - id: 1
    passed: true
    reasoning: "Yes"
final_score: 0.8
summary: "Mostly passed."
```
"""
    mock_llm = MockJudgeLLM(assertion_yaml)
    prompts = {
        "assertion_check": (
            "Query: {query}\nResponse: {response}\nAssertions: {assertions}"
        )
    }
    evaluator = Evaluator(None, mock_llm, None, None, prompts=prompts)

    score, summary, results = asyncio.run(
        evaluator._evaluate_assertions("query", "response", [MockAssertion()])
    )
    # score is pass_rate = passed_count / total (1/1 = 1.0)
    assert score == pytest.approx(1.0)
    assert summary == "Mostly passed."
    assert len(results) >= 1
