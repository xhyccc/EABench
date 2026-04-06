"""Comprehensive tests for src.eval.evaluator.Evaluator.

Bugs found and fixed in evaluator.py:
  BUG-001  _evaluate_citation regex matched [^N^] Title [Type: T, ID: id] which
           no real agent response ever contains.  Actual format (from system prompt)
           is a References section line: - *Type*: T (ID: id).
           Fixed: regex changed to r"\\*Type\\*:\\s+([^\\n(]+?)\\s+\\(ID:\\s+([^)\\n]+?)\\)".

  BUG-002  _fetch_entity_content file branch called self.sandbox.read_file() even
           when self.sandbox is None, raising AttributeError.
           Fixed: early-return None when sandbox is absent.
"""

import asyncio
import textwrap
import pytest

from src.config.tenant_config import (
    TenantConfig, Email, Chat, ChatMessage, GroupChat,
    Meeting, Channel, ChannelPost,
)
from src.core.agent_runner import AgentRunResult
from src.core.llm_provider import LLMProvider, LLMResponse, Message
from src.eval.evaluator import Evaluator
from src.eval.models import (
    Assertion, EvaluationCase, EvaluationResult, EvaluationSet,
)

# ---------------------------------------------------------------------------
# Shared fixtures / factories
# ---------------------------------------------------------------------------

_ASSERTION_PROMPT = "Query: {query}\nResponse: {response}\nAssertions: {assertions}"


class MockJudgeLLM(LLMProvider):
    """Returns a fixed string for every generate() call."""

    def __init__(self, response_content: str = ""):
        self.response_content = response_content
        self.call_count = 0

    async def generate(self, history, tools):
        self.call_count += 1
        return LLMResponse(content=self.response_content)


class SequentialMockLLM(LLMProvider):
    """Returns responses from a predefined list in order."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self._idx = 0

    async def generate(self, history, tools):
        content = self.responses[self._idx % len(self.responses)]
        self._idx += 1
        return LLMResponse(content=content)


class ErrorLLM(LLMProvider):
    async def generate(self, history, tools):
        raise RuntimeError("LLM network error")


class MockSearchEngine:
    def __init__(self, tenant=None):
        self.tenant = tenant
        self.current_user_id = None

    def set_user_context(self, user_id: str):
        self.current_user_id = user_id


class MockRunner:
    history: list = []

    async def run(self, query, sandbox, search_engine):
        self.history = []
        return AgentRunResult(response="The budget is healthy.", metrics={"tool_calls_count": 1})


class FailingRunner:
    history: list = []

    async def run(self, query, sandbox, search_engine):
        self.history = []
        raise RuntimeError("Agent crashed!")


def _make_tenant():
    """Minimal tenant with one entity of each type."""
    return TenantConfig(
        id="test-tenant",
        domain="test.com",
        emails=[
            Email(
                id="email_001",
                from_user="alice@test.com",
                to_users=["bob@test.com"],
                subject="Budget Report",
                body="The budget is healthy.",
                timestamp="2024-01-01T10:00:00",
            )
        ],
        chats=[
            Chat(
                id="chat_001",
                participants=["alice", "bob"],
                messages=[
                    ChatMessage(
                        from_user="alice", to_user="bob",
                        content="Hello!", timestamp="2024-01-01T10:00:00",
                    )
                ],
            )
        ],
        group_chats=[
            GroupChat(
                id="gc_001",
                name="Engineering",
                participants=["alice", "bob"],
                messages=[
                    ChatMessage(
                        from_user="alice", content="Meeting at 3pm",
                        timestamp="2024-01-01T10:00:00",
                    )
                ],
            )
        ],
        channels=[
            Channel(
                id="ch_001",
                name="general",
                participants=["alice"],
                posts=[
                    ChannelPost(
                        id="post_001", author="alice",
                        content="Hello world!", timestamp="2024-01-01T10:00:00",
                    )
                ],
            )
        ],
        meetings=[
            Meeting(
                id="mtg_001",
                title="Q1 Review",
                organizer="alice",
                start_time="2024-01-01T10:00:00",
                end_time="2024-01-01T11:00:00",
                agenda="Review Q1 results",
                transcript="We discussed the budget.",
            )
        ],
    )


def _make_evaluator(yaml_content: str = "", prompts: dict = None, search_engine=None):
    return Evaluator(
        runner=None,
        llm=MockJudgeLLM(yaml_content),
        sandbox=None,
        search_engine=search_engine,
        prompts=prompts if prompts is not None else {"assertion_check": _ASSERTION_PROMPT},
    )


def _make_eval_result(case_id="case_001", score=0.8, passed=True):
    return EvaluationResult(
        case_id=case_id,
        query="Summarise the budget report",
        response="The budget is healthy.",
        tool_calls=[],
        metrics={"assertion_score": score, "citation_score": 1.0},
        reasoning="All assertions passed.",
        passed=passed,
    )


def _assertions(n: int):
    class A:
        description = "test assertion"
    return [A() for _ in range(n)]


def _assertion_yaml(passed: bool, summary: str, n: int = 1) -> str:
    entries = "\n".join(
        f"  - id: {i + 1}\n    passed: {'true' if passed else 'false'}\n    reasoning: checked"
        for i in range(n)
    )
    return f"```yaml\nassertions:\n{entries}\nsummary: '{summary}'\n```"


# Response with citations in the CORRECT format defined by the system prompt
_CITED_RESPONSE = textwrap.dedent("""
    The budget appears healthy[^1^].

    ## References

    1. **Budget Report**
       - *Source*: Alice (2024-01-01T10:00:00)
       - *Type*: Email (ID: email_001)
""")

# Response with citations in the OLD bracket format (no agent ever produces this)
_OLD_FORMAT_RESPONSE = "[^1^] Budget Report [Type: email, ID: email_001]"


# ===========================================================================
# 1.  _parse_yaml_response
# ===========================================================================

class TestParseYamlResponse:
    def test_extracts_from_yaml_code_block(self):
        ev = _make_evaluator()
        assert ev._parse_yaml_response("```yaml\nkey: value\n```") == {"key": "value"}

    def test_extracts_from_json_code_block(self):
        ev = _make_evaluator()
        assert ev._parse_yaml_response('```json\n{"key": "value"}\n```') == {"key": "value"}

    def test_falls_back_to_raw_text_when_no_fence(self):
        ev = _make_evaluator()
        assert ev._parse_yaml_response("key: value") == {"key": "value"}

    def test_invalid_yaml_returns_empty_dict(self):
        ev = _make_evaluator()
        assert ev._parse_yaml_response("```yaml\n: : bad yaml {{\n```") == {}

    def test_return_type_is_dict(self):
        ev = _make_evaluator()
        assert isinstance(ev._parse_yaml_response("```yaml\nscore: 0.8\n```"), dict)

    def test_handles_indented_yaml_in_fence(self):
        ev = _make_evaluator()
        result = ev._parse_yaml_response("```yaml\n  score: 0.5\n  reason: 'ok'\n```")
        assert result["score"] == pytest.approx(0.5)

    def test_empty_string_returns_empty_dict_or_none(self):
        """Empty / whitespace-only content must not raise."""
        ev = _make_evaluator()
        result = ev._parse_yaml_response("")
        # yaml.safe_load("") returns None; we accept either None or {}
        assert result in (None, {})


# ===========================================================================
# 2.  _fetch_entity_content
# ===========================================================================

class TestFetchEntityContent:
    def setup_method(self):
        tenant = _make_tenant()
        self.ev = _make_evaluator(search_engine=MockSearchEngine(tenant))

    def test_email_found_returns_subject_and_body(self):
        content = self.ev._fetch_entity_content("email", "email_001")
        assert "Budget Report" in content
        assert "The budget is healthy." in content

    def test_chat_found(self):
        assert "Hello!" in self.ev._fetch_entity_content("chat", "chat_001")

    def test_group_chat_found_with_underscore_type(self):
        assert "Meeting at 3pm" in self.ev._fetch_entity_content("group_chat", "gc_001")

    def test_group_chat_found_with_space_type(self):
        """'group chat' (space) must also resolve — matches system prompt output."""
        assert "Meeting at 3pm" in self.ev._fetch_entity_content("group chat", "gc_001")

    def test_channel_found(self):
        assert "Hello world!" in self.ev._fetch_entity_content("channel", "ch_001")

    def test_meeting_found_includes_transcript(self):
        content = self.ev._fetch_entity_content("meeting", "mtg_001")
        assert "Q1 Review" in content
        assert "We discussed the budget." in content

    def test_unknown_id_returns_none(self):
        assert self.ev._fetch_entity_content("email", "nonexistent_99") is None

    def test_unknown_entity_type_returns_none(self):
        assert self.ev._fetch_entity_content("invoice", "inv_001") is None

    def test_no_tenant_returns_none(self):
        ev = _make_evaluator(search_engine=MockSearchEngine(tenant=None))
        assert ev._fetch_entity_content("email", "email_001") is None

    def test_file_entity_with_no_sandbox_returns_none(self):
        """BUG-002: Must return None rather than AttributeError when sandbox is None."""
        assert self.ev._fetch_entity_content("file", "docs/report.md") is None


# ===========================================================================
# 3.  _evaluate_citation   (includes BUG-001 regression tests)
# ===========================================================================

class TestEvaluateCitation:
    def test_no_citations_returns_zero_score(self):
        ev = _make_evaluator()
        tool_score, response_score, combined, msg = asyncio.run(ev._evaluate_citation("q", [], "plain response"))
        assert combined == pytest.approx(0.0)
        assert "No structured citations" in msg

    def test_return_types_are_float_and_str(self):
        ev = _make_evaluator()
        tool_score, response_score, combined, msg = asyncio.run(ev._evaluate_citation("q", [], "r"))
        assert isinstance(combined, float)
        assert isinstance(msg, str)

    # ── BUG-001 regression ────────────────────────────────────────────────

    def test_old_bracket_format_does_not_score(self):
        """BUG-001: [^N^] Title [Type: T, ID: id] was the old expected format.
        No agent ever produces this; after the fix it must NOT match."""
        ev = _make_evaluator()
        _, _, combined, _ = asyncio.run(ev._evaluate_citation("q", [], _OLD_FORMAT_RESPONSE))
        assert combined == pytest.approx(0.0), (
            "Old bracket format should not produce a non-zero citation score"
        )

    def test_new_reference_section_format_is_detected(self):
        """BUG-001 fix: *Type*: T (ID: id) inside a References section must match."""
        tenant = _make_tenant()
        se = MockSearchEngine(tenant)
        ev = _make_evaluator("```yaml\nscore: 0.9\nreason: relevant\n```", search_engine=se)
        _, response_score, _, _ = asyncio.run(ev._evaluate_citation("budget", [], _CITED_RESPONSE))
        assert response_score > 0.0, "Citations in the correct format must yield response_score > 0"

    # ── Hallucination detection ───────────────────────────────────────────

    def test_nonexistent_entity_id_is_hallucination(self):
        response = textwrap.dedent("""
            See ref[^1^].

            ## References

            1. **Ghost**
               - *Source*: Nobody
               - *Type*: Email (ID: does_not_exist_999)
        """)
        tenant = _make_tenant()
        ev = _make_evaluator("score: 0.9", search_engine=MockSearchEngine(tenant))
        _, response_score, combined, explanation = asyncio.run(ev._evaluate_citation("q", [], response))
        assert response_score == pytest.approx(0.0)
        assert combined == pytest.approx(0.0)
        assert "Hallucination" in explanation or "not found" in explanation.lower()

    # ── Aggregation ───────────────────────────────────────────────────────

    def test_multiple_citations_are_averaged(self):
        """One real citation (score 0.8) + one hallucination (0.0) → response_score=0.4, combined=0.2."""
        response = textwrap.dedent("""
            Ref A[^1^] and B[^2^].

            ## References

            1. **Email**
               - *Source*: Alice
               - *Type*: Email (ID: email_001)

            2. **Ghost**
               - *Source*: Nobody
               - *Type*: Email (ID: does_not_exist)
        """)
        tenant = _make_tenant()
        ev = _make_evaluator(
            "```yaml\nscore: 0.8\nreason: relevant\n```",
            search_engine=MockSearchEngine(tenant),
        )
        tool_score, response_score, combined, _ = asyncio.run(ev._evaluate_citation("budget", [], response))
        # No tool calls → tool_score=0.0; response: one real (0.8) + one hallucinated (0.0) → 0.4
        assert response_score == pytest.approx(0.4)
        assert combined == pytest.approx(0.2)  # (0.0 + 0.4) / 2

    def test_malformed_judge_yaml_returns_float(self):
        tenant = _make_tenant()
        ev = _make_evaluator("not yaml {{", search_engine=MockSearchEngine(tenant))
        _, _, combined, _ = asyncio.run(ev._evaluate_citation("q", [], _CITED_RESPONSE))
        assert isinstance(combined, float)

    def test_score_is_bounded_zero_to_one(self):
        tenant = _make_tenant()
        ev = _make_evaluator(
            "```yaml\nscore: 1.0\nreason: ok\n```",
            search_engine=MockSearchEngine(tenant),
        )
        _, _, combined, _ = asyncio.run(ev._evaluate_citation("q", [], _CITED_RESPONSE))
        assert 0.0 <= combined <= 1.0


# ===========================================================================
# 4.  _evaluate_assertions
# ===========================================================================

class TestEvaluateAssertions:
    def test_missing_prompt_returns_zero(self):
        ev = _make_evaluator(prompts={})
        score, msg, results = asyncio.run(ev._evaluate_assertions("q", "r", _assertions(1)))
        assert score == pytest.approx(0.0)
        assert "not configured" in msg

    def test_single_assertion_pass(self):
        ev = _make_evaluator(_assertion_yaml(True, "Great."))
        score, summary, _ = asyncio.run(ev._evaluate_assertions("q", "r", _assertions(1)))
        assert score == pytest.approx(1.0)
        assert summary == "Great."

    def test_single_assertion_fail(self):
        ev = _make_evaluator(_assertion_yaml(False, "Nothing."))
        score, _, _ = asyncio.run(ev._evaluate_assertions("q", "r", _assertions(1)))
        assert score == pytest.approx(0.0)

    def test_partial_pass_gives_fractional_score(self):
        yaml_content = textwrap.dedent("""
            ```yaml
            assertions:
              - id: 1
                passed: true
                reasoning: ok
              - id: 2
                passed: false
                reasoning: failed
            summary: 'Half passed.'
            ```
        """)
        ev = _make_evaluator(yaml_content)
        score, _, _ = asyncio.run(ev._evaluate_assertions("q", "r", _assertions(2)))
        assert score == pytest.approx(0.5)

    def test_empty_assertions_list_returns_zero(self):
        ev = _make_evaluator(_assertion_yaml(True, "n/a"))
        score, _, results = asyncio.run(ev._evaluate_assertions("q", "r", []))
        assert score == pytest.approx(0.0)

    def test_bad_yaml_from_judge_returns_zero(self):
        ev = _make_evaluator("this is not valid yaml {{ }")
        score, _, results = asyncio.run(ev._evaluate_assertions("q", "r", _assertions(1)))
        assert score == pytest.approx(0.0)
        assert isinstance(results, list)

    def test_assertion_results_enriched_with_description(self):
        ev = _make_evaluator(_assertion_yaml(True, "Passed."))
        _, _, results = asyncio.run(ev._evaluate_assertions("q", "r", _assertions(1)))
        assert results[0].get("description") == "test assertion"

    def test_returns_three_tuple(self):
        ev = _make_evaluator(_assertion_yaml(True, "ok"))
        result = asyncio.run(ev._evaluate_assertions("q", "r", _assertions(1)))
        assert len(result) == 3
        score, summary, lst = result
        assert isinstance(score, float)
        assert isinstance(summary, str)
        assert isinstance(lst, list)


# ===========================================================================
# 5.  calculate_p_value
# ===========================================================================

class TestCalculatePValue:
    def test_identical_returns_one(self):
        ev = _make_evaluator()
        assert ev.calculate_p_value([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]) == pytest.approx(1.0)

    def test_different_returns_float_in_range(self):
        ev = _make_evaluator()
        p = ev.calculate_p_value([0.1, 0.2, 0.3], [0.8, 0.9, 1.0])
        assert isinstance(p, float)
        assert 0.0 <= p <= 1.0

    def test_single_element_returns_none(self):
        assert _make_evaluator().calculate_p_value([0.5], [0.5]) is None

    def test_mismatched_lengths_returns_none(self):
        assert _make_evaluator().calculate_p_value([0.5, 0.6], [0.7]) is None

    def test_empty_lists_returns_none(self):
        assert _make_evaluator().calculate_p_value([], []) is None

    def test_all_zeros_returns_one(self):
        p = _make_evaluator().calculate_p_value([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        assert p == pytest.approx(1.0)


# ===========================================================================
# 6.  compare_two
# ===========================================================================

class TestCompareTwo:
    def _case(self):
        return EvaluationCase(
            id="c1", query="What is the budget?",
            assertions=[Assertion(description="mentions budget")],
        )

    def test_missing_side_by_side_prompt_returns_tie(self):
        ev = _make_evaluator(prompts={})
        result = asyncio.run(
            ev.compare_two(self._case(), _make_eval_result("a"), _make_eval_result("b"))
        )
        assert result.winner == "Tie"
        assert "Missing" in result.reasoning

    def test_valid_judgment_parses_winner_and_score(self):
        yaml_resp = "```yaml\nwinner: 'A'\nreasoning: 'A was better'\nbetter_response_score: 0.9\n```"
        ev = _make_evaluator(
            yaml_resp,
            prompts={"side_by_side": "q:{query} ra:{response_a} rb:{response_b} a:{assertions}"},
        )
        result = asyncio.run(
            ev.compare_two(self._case(), _make_eval_result("a"), _make_eval_result("b"))
        )
        assert result.winner == "A"
        assert result.score == pytest.approx(0.9)

    def test_llm_error_returns_error_tie(self):
        ev = Evaluator(
            runner=None, llm=ErrorLLM(), sandbox=None, search_engine=None,
            prompts={"side_by_side": "q:{query} ra:{response_a} rb:{response_b} a:{assertions}"},
        )
        result = asyncio.run(
            ev.compare_two(self._case(), _make_eval_result("a"), _make_eval_result("b"))
        )
        assert result.winner == "Tie"
        assert "Error" in result.reasoning

    def test_case_and_query_preserved_in_result(self):
        yaml_resp = "```yaml\nwinner: 'B'\nreasoning: 'B better'\nbetter_response_score: 0.7\n```"
        ev = _make_evaluator(
            yaml_resp,
            prompts={"side_by_side": "q:{query} ra:{response_a} rb:{response_b} a:{assertions}"},
        )
        result = asyncio.run(
            ev.compare_two(self._case(), _make_eval_result("a"), _make_eval_result("b"))
        )
        assert result.case_id == "c1"
        assert result.query == "What is the budget?"

    def test_zero_score_when_no_side_by_side_prompt(self):
        ev = _make_evaluator(prompts={})
        result = asyncio.run(
            ev.compare_two(self._case(), _make_eval_result("a"), _make_eval_result("b"))
        )
        assert result.score == pytest.approx(0.0)


# ===========================================================================
# 7.  evaluate_single
# ===========================================================================

class TestEvaluateSingle:
    def _make_full_evaluator(self, runner, judge_yaml):
        se = MockSearchEngine(_make_tenant())
        return Evaluator(
            runner=runner, llm=MockJudgeLLM(judge_yaml),
            sandbox=None, search_engine=se,
            prompts={"assertion_check": _ASSERTION_PROMPT},
        ), se

    def _case(self, user_id=None):
        return EvaluationCase(
            id="test_case",
            query="What is the budget?",
            user_id=user_id,
            assertions=[Assertion(description="mentions budget")],
        )

    def test_returns_evaluation_result_instance(self):
        ev, _ = self._make_full_evaluator(MockRunner(), _assertion_yaml(True, "ok"))
        result = asyncio.run(ev.evaluate_single(self._case()))
        assert isinstance(result, EvaluationResult)
        assert result.case_id == "test_case"

    def test_sets_user_context_when_user_id_provided(self):
        ev, se = self._make_full_evaluator(MockRunner(), _assertion_yaml(True, "ok"))
        asyncio.run(ev.evaluate_single(self._case(user_id="alice")))
        assert se.current_user_id == "alice"

    def test_runner_exception_produces_error_response(self):
        ev, _ = self._make_full_evaluator(FailingRunner(), "score: 0.0\nreason: n/a")
        result = asyncio.run(ev.evaluate_single(self._case()))
        assert "Error" in result.response

    def test_resets_runner_history_each_case(self):
        runner = MockRunner()
        runner.history = [{"stale": True}]
        ev, _ = self._make_full_evaluator(runner, _assertion_yaml(True, "ok"))
        asyncio.run(ev.evaluate_single(self._case()))
        assert runner.history == []

    def test_metrics_contain_required_keys(self):
        ev, _ = self._make_full_evaluator(MockRunner(), _assertion_yaml(True, "ok"))
        result = asyncio.run(ev.evaluate_single(self._case()))
        assert "assertion_score" in result.metrics
        assert "citation_score" in result.metrics
        assert "tool_citation_score" in result.metrics
        assert "response_citation_score" in result.metrics
        assert "latency" in result.metrics

    def test_no_citations_in_response_forces_failed(self):
        """With no citations, response_citation_score=0.0 < 0.7 threshold → passed=False
        even when all assertions pass (assertion_score=1.0)."""
        ev, _ = self._make_full_evaluator(MockRunner(), _assertion_yaml(True, "ok"))
        result = asyncio.run(ev.evaluate_single(self._case()))
        assert result.metrics["citation_score"] == pytest.approx(0.0)
        assert result.metrics["response_citation_score"] == pytest.approx(0.0)
        assert result.passed is False


# ===========================================================================
# 8.  evaluate_batch
# ===========================================================================

class TestEvaluateBatch:
    def _set(self, n: int):
        return EvaluationSet(
            name="test", description="batch",
            cases=[
                EvaluationCase(
                    id=f"case_{i:03d}", query=f"Q{i}",
                    assertions=[Assertion(description="a")],
                )
                for i in range(n)
            ],
        )

    def _make_ev(self):
        return Evaluator(
            runner=MockRunner(), llm=MockJudgeLLM("score: 0.5\nreason: ok"),
            sandbox=None, search_engine=MockSearchEngine(_make_tenant()),
            prompts={"assertion_check": _ASSERTION_PROMPT},
        )

    def test_correct_result_count(self):
        assert len(asyncio.run(self._make_ev().evaluate_batch(self._set(3)))) == 3

    def test_result_order_matches_input(self):
        results = asyncio.run(self._make_ev().evaluate_batch(self._set(3)))
        assert [r.case_id for r in results] == ["case_000", "case_001", "case_002"]

    def test_empty_set_returns_empty_list(self):
        assert asyncio.run(self._make_ev().evaluate_batch(self._set(0))) == []


# ===========================================================================
# 9.  EvaluationResult / model unit tests
# ===========================================================================

class TestEvaluationModels:
    def test_assertion_weight_default_is_one(self):
        assert Assertion(description="x").weight == pytest.approx(1.0)

    def test_assertion_accepts_custom_weight(self):
        assert Assertion(description="x", weight=2.5).weight == pytest.approx(2.5)

    def test_evaluation_case_construction(self):
        case = EvaluationCase(
            id="c1", query="Q?",
            assertions=[Assertion(description="mentions budget")],
        )
        assert case.id == "c1"
        assert case.user_id is None
        assert len(case.assertions) == 1

    def test_evaluation_result_fields(self):
        r = _make_eval_result(case_id="x42", score=0.5)
        assert r.case_id == "x42"
        assert "assertion_score" in r.metrics
        assert r.tool_calls == []

    def test_evaluation_set_construction(self):
        es = EvaluationSet(
            name="n", description="d",
            cases=[EvaluationCase(id="c", query="q", assertions=[Assertion(description="a")])],
        )
        assert len(es.cases) == 1


# ===========================================================================
# 10.  passed threshold logic (white-box)
# ===========================================================================

class TestPassedThreshold:
    """The passed flag requires assertion_score >= 0.75 AND citation_score >= 0.7."""

    def test_high_assertion_no_citation_is_failed(self):
        """assertion_score=1.0 but citation_score=0.0 → passed must be False."""
        ev = Evaluator(
            runner=MockRunner(),
            llm=MockJudgeLLM(_assertion_yaml(True, "ok")),
            sandbox=None,
            search_engine=MockSearchEngine(_make_tenant()),
            prompts={"assertion_check": _ASSERTION_PROMPT},
        )
        case = EvaluationCase(id="t", query="q", assertions=[Assertion(description="d")])
        result = asyncio.run(ev.evaluate_single(case))
        assert result.metrics["assertion_score"] >= 0.75
        assert result.metrics["citation_score"] == pytest.approx(0.0)
        assert result.passed is False

    def test_both_thresholds_met_is_passed(self):
        """When agent response contains a valid citation AND assertions pass → passed=True."""
        tenant = _make_tenant()
        se = MockSearchEngine(tenant)

        citation_score_yaml = "```yaml\nscore: 1.0\nreason: ok\n```"
        assertion_score_yaml = _assertion_yaml(True, "All passed.")

        # First judge call = citation relevance, second = assertion check
        llm = SequentialMockLLM([citation_score_yaml, assertion_score_yaml])

        class CitedRunner:
            history: list = []

            async def run(self, query, sandbox, search_engine):
                self.history = []
                return AgentRunResult(response=_CITED_RESPONSE, metrics={})

        ev = Evaluator(
            runner=CitedRunner(), llm=llm,
            sandbox=None, search_engine=se,
            prompts={"assertion_check": _ASSERTION_PROMPT},
        )
        case = EvaluationCase(id="t", query="budget", assertions=[Assertion(description="d")])
        result = asyncio.run(ev.evaluate_single(case))
        assert result.metrics["citation_score"] > 0.0
        assert result.metrics["assertion_score"] >= 0.75
        assert result.passed is True

