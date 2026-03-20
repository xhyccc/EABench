"""Tests for src.eval.evaluator.Evaluator (using mock LLM)."""

import asyncio
import pytest

from src.core.llm_provider import LLMProvider, LLMResponse, Message
from src.eval.evaluator import Evaluator
from src.eval.models import Assertion, EvaluationCase, EvaluationResult


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class MockJudgeLLM(LLMProvider):
    """LLM mock that returns a pre-configured YAML string."""

    def __init__(self, response_content: str):
        self.response_content = response_content

    async def generate(self, history, tools):
        return LLMResponse(content=self.response_content)


_ASSERTION_CHECK_PROMPT = "Query: {query}\nResponse: {response}\nAssertions: {assertions}"


def _make_evaluator(yaml_content: str, prompts: dict = None) -> Evaluator:
    """Return an Evaluator wired to a MockJudgeLLM returning *yaml_content*."""
    mock_llm = MockJudgeLLM(yaml_content)
    return Evaluator(
        runner=None,
        llm=mock_llm,
        sandbox=None,
        search_engine=None,
        prompts=prompts or {"assertion_check": _ASSERTION_CHECK_PROMPT},
    )


def _make_eval_result(case_id="case_001", score=0.8) -> EvaluationResult:
    return EvaluationResult(
        case_id=case_id,
        query="Summarise the budget report",
        response="The budget is healthy.",
        tool_calls=[],
        metrics={"assertion_score": score, "citation_score": 1.0},
        reasoning="All assertions passed.",
        passed=True,
    )


# ---------------------------------------------------------------------------
# Citation evaluation tests
# ---------------------------------------------------------------------------


class TestEvaluateCitation:
    def test_no_citations_returns_zero_score(self):
        """When the response has no structured citations, score is 0.0."""
        evaluator = _make_evaluator("")
        score, explanation = asyncio.run(
            evaluator._evaluate_citation("query", [], "plain response without any citations")
        )
        assert score == pytest.approx(0.0)
        assert "No structured citations" in explanation

    def test_returns_float_and_string(self):
        """Return types are always (float, str)."""
        evaluator = _make_evaluator("")
        score, explanation = asyncio.run(
            evaluator._evaluate_citation("q", [], "r")
        )
        assert isinstance(score, float)
        assert isinstance(explanation, str)

    def test_malformed_yaml_returns_defaults(self):
        """Malformed LLM output should not raise – return a safe default."""
        evaluator = _make_evaluator("this is not yaml at all ¯\\_(ツ)_/¯")
        score, explanation = asyncio.run(evaluator._evaluate_citation("q", [], "r"))
        assert isinstance(score, float)
        assert isinstance(explanation, str)


# ---------------------------------------------------------------------------
# Assertion evaluation tests
# ---------------------------------------------------------------------------


class TestEvaluateAssertions:
    def _make_yaml(self, passed: bool, score: float, summary: str) -> str:
        passed_str = "true" if passed else "false"
        return f"""
```yaml
assertions:
  - id: 1
    passed: {passed_str}
    reasoning: "checked"
final_score: {score}
summary: "{summary}"
```
"""

    def test_parses_score_and_summary(self):
        evaluator = _make_evaluator(self._make_yaml(True, 0.8, "Mostly passed."))

        class MockAssertion:
            description = "file must contain keyword"

        score, summary, results = asyncio.run(
            evaluator._evaluate_assertions("query", "response", [MockAssertion()])
        )
        # score = passed_count / total = 1/1 = 1.0
        assert score == pytest.approx(1.0)
        assert summary == "Mostly passed."

    def test_full_fail(self):
        evaluator = _make_evaluator(self._make_yaml(False, 0.0, "Nothing passed."))

        class MockAssertion:
            description = "test assertion"

        score, summary, results = asyncio.run(
            evaluator._evaluate_assertions("q", "r", [MockAssertion()])
        )
        assert score == pytest.approx(0.0)

    def test_returns_three_values(self):
        evaluator = _make_evaluator(self._make_yaml(True, 1.0, "All passed."))

        class MockAssertion:
            description = "test"

        result = asyncio.run(evaluator._evaluate_assertions("q", "r", [MockAssertion()]))
        assert len(result) == 3  # (score, summary, assertion_results)

    def test_assertion_results_list_returned(self):
        evaluator = _make_evaluator(self._make_yaml(True, 1.0, "Passed."))

        class MockAssertion:
            description = "test"

        _, _, results = asyncio.run(
            evaluator._evaluate_assertions("q", "r", [MockAssertion()])
        )
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# p-value / statistical tests
# ---------------------------------------------------------------------------


class TestCalculatePValue:
    def test_identical_scores_return_one(self):
        evaluator = _make_evaluator("")
        p = evaluator.calculate_p_value([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
        assert p == pytest.approx(1.0)

    def test_different_scores_return_float(self):
        evaluator = _make_evaluator("")
        p = evaluator.calculate_p_value([0.1, 0.2, 0.3], [0.8, 0.9, 1.0])
        assert isinstance(p, float)
        assert 0.0 <= p <= 1.0

    def test_too_few_samples_returns_none(self):
        evaluator = _make_evaluator("")
        p = evaluator.calculate_p_value([0.5], [0.5])
        assert p is None

    def test_mismatched_length_returns_none(self):
        evaluator = _make_evaluator("")
        p = evaluator.calculate_p_value([0.5, 0.6], [0.7])
        assert p is None


# ---------------------------------------------------------------------------
# EvaluationResult model tests
# ---------------------------------------------------------------------------


class TestEvaluationModels:
    def test_assertion_defaults(self):
        a = Assertion(description="file exists")
        assert a.weight == 1.0

    def test_evaluation_case_construction(self):
        case = EvaluationCase(
            id="c1",
            query="What is the budget?",
            assertions=[Assertion(description="mentions budget")],
        )
        assert case.id == "c1"
        assert len(case.assertions) == 1

    def test_evaluation_result_passed(self):
        r = _make_eval_result(score=1.0)
        assert r.passed is True

    def test_evaluation_result_fields(self):
        r = _make_eval_result(case_id="x", score=0.5)
        assert r.case_id == "x"
        assert "assertion_score" in r.metrics
