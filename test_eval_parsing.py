import asyncio
import sys
import os

# Add src to path
sys.path.append(os.getcwd())

from src.core.llm_provider import LLMProvider, LLMResponse, Message
from src.eval.evaluator import Evaluator

class MockJudgeLLM(LLMProvider):
    def __init__(self, response_content):
        self.response_content = response_content

    async def generate(self, history, tools):
        return LLMResponse(content=self.response_content)

async def test_parsing():
    print("Testing YAML parsing in Evaluator...")
    
    # Test Citation Parsing
    citation_yaml = """
    ```yaml
    score: 0.9
    explanation: "Good job."
    ```
    """
    mock_llm = MockJudgeLLM(citation_yaml)
    # Pass None for dependencies we don't use in this test
    evaluator = Evaluator(None, mock_llm, None, None)
    
    score, explanation = await evaluator._evaluate_citation("query", [], "response")
    print(f"Citation - Score: {score}, Explanation: {explanation}")
    assert score == 0.9
    assert explanation == "Good job."

    # Test Assertion Parsing
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
    mock_llm.response_content = assertion_yaml
    
    # Mock assertions object
    class MockAssertion:
        description = "test"
        
    score, summary = await evaluator._evaluate_assertions("query", "response", [MockAssertion()])
    print(f"Assertion - Score: {score}, Summary: {summary}")
    assert score == 0.8
    assert summary == "Mostly passed."
    
    print("All tests passed!")

if __name__ == "__main__":
    asyncio.run(test_parsing())
