# Evaluation Harness

## Overview

The EABench evaluation harness is an **LLM-as-a-Judge** framework that measures the quality of an enterprise agent's responses across three orthogonal dimensions: assertion fulfilment, tool-usage quality, and response citation integrity. The harness is highly configurable: judge prompts, scoring thresholds, and the judge model are all declared in a YAML file, making it straightforward to swap judge models or extend the metric set without code changes.

The implementation lives in `python/src/eval/evaluator.py`, driven by `python/run_eval.py`.

---

## Components

| Component | File | Responsibility |
|---|---|---|
| `Evaluator` | `evaluator.py` | Orchestrates per-case evaluation |
| `EvaluationCase` | `eval/models.py` | Query + assertions + ground truth |
| `EvaluationResult` | `eval/models.py` | Per-case scores and artefacts |
| `EvaluationSet` | `eval/models.py` | Named collection of cases |
| Judge YAML | `examples/evals/default_judge.yaml` | All judge prompts + judge model config |
| `run_eval.py` | root | CLI entry point + result serialisation |

---

## Judge Configuration

The judge is configured independently of the agent under evaluation:

```yaml
name: "Default Judge Prompts"
description: "Standard prompts for citation relevance and assertion checking"
model:
  provider: azure
  name: gpt-4o
  parameters:
    temperature: 0.0      # deterministic scoring

prompts:
  citation_relevance:   |<prompt>
  assertion_check:      |<prompt>
  side_by_side:         |<prompt>
  response_citation:    |<prompt>
```

Setting `temperature: 0.0` ensures consistent, reproducible judgments. The judge model can differ from the agent model (e.g., use a stronger model as judge).

---

## Evaluation Loop

For each `EvaluationCase` in the `EvaluationSet`, `Evaluator.evaluate_single(case)` executes the following pipeline:

```
1. Set user context on the search engine (case.user_id)
2. Clear agent history (each case is independent)
3. Run agent: AgentRunner.run(case.query) → response + tool_calls
4. Evaluate tool citation quality (LLM judge)
5. Evaluate response citation quality (LLM judge)
6. Count raw metrics (tool search result count, response citation count)
7. Evaluate assertions (LLM judge)
8. Aggregate → EvaluationResult
```

Wall-clock latency of step 3 is measured and included in the metrics.

---

## Metrics

### 1. Assertion Score (`assertion_score`)

**Judge prompt**: `assertion_check`

The judge receives the user query, the agent's final response, and a numbered list of assertions. For each assertion, it decides `passed: true/false` with a brief reasoning string.

```
User Query: "Show me the email from Hyun-Jae Wang about debugging improvements..."

Assertions:
1. Returns the email 'Technical Feedback on Debugging Update' from hwang
2. Identifies the date as March 25, 2026
3. Contains at least one of the issues raised

Judge output (YAML):
assertions:
  - id: 1
    passed: true
    reasoning: "Response correctly identifies email_004 from hwang."
  - id: 2
    passed: true
    reasoning: "Date March 25 is mentioned explicitly."
  - id: 3
    passed: false
    reasoning: "Response does not mention specific issues."
final_score: 0.667
summary: "2 of 3 assertions passed."
```

The final `assertion_score` is computed as the **pass rate** (`passed_count / total_assertions`), irrespective of the judge's `final_score` field.

### 2. Tool Search Result Number (`tool_search_result_number`)

A **deterministic, regex-based** count of the total number of search result items returned across all tool calls. Each search result item includes a `'score':` key; counting occurrences of this pattern provides an accurate item count without additional LLM calls.

```python
total += len(re.findall(r"'score'\s*:", result))
```

This is a diagnostic metric: a high value means the agent retrieved many items; a low value may indicate over-narrowed queries.

### 3. Tool Search Result Relevance (`tool_search_result_relevance`)

**Judge prompt**: `citation_relevance`

The judge evaluates the **quality of tool usage**:
1. Did the agent use appropriate tools (e.g., `search_email` for email questions)?
2. Were the retrieved results relevant to the query?
3. Does the final response faithfully reflect the tool results, or did the agent hallucinate?

Scoring guide:
| Score | Meaning |
|---|---|
| 1.0 | Correct tools, relevant results, response faithful to results |
| 0.7–0.9 | Mostly correct with minor gaps |
| 0.4–0.6 | Partial: some correct retrieval but hallucinated or irrelevant details |
| 0.0–0.3 | Wrong tools, irrelevant results, or response contradicts/ignores tool output |

### 4. Response Citation Number (`response_citation_number`)

A **deterministic, regex-based** count of the number of entries in the agent's `## References` section, matched against the canonical citation format:

```
- *Type*: <type> (ID: <id>)
```

This measures how thoroughly the agent cited its sources.

### 5. Response Citation Relevance (`response_citation_score`)

**Judge prompt**: `response_citation`

The judge evaluates the **quality of the response's References section**:
1. Is a `## References` section present?
2. Are the cited IDs real (verifiable in tool results)?
3. Are the cited items relevant to the query?
4. Are inline citation markers (`[^N^]`) present in the body text?

Scoring guide:
| Score | Meaning |
|---|---|
| 1.0 | References present, all IDs real, all relevant, inline citations present |
| 0.7–0.9 | Minor issues: 1 fake ID, missing inline for 1–2 items, or one irrelevant citation |
| 0.4–0.6 | Significant issues: multiple fake IDs, mostly missing inline citations |
| 0.1–0.3 | References barely present or mostly hallucinated IDs |
| 0.0 | No References section at all |

### Combined Citation Score (`citation_score`)

A simple average of `tool_citation_score` (alias for `tool_search_result_relevance`) and `response_citation_score`.

---

## Pass / Fail Criterion

A case is marked **PASS** if both conditions hold:

```python
passed = assertion_score >= 0.75 and response_citation_score >= 0.7
```

This dual threshold enforces that the agent must both answer correctly *and* properly cite its sources. An agent that gives correct answers without citations (or cites hallucinated IDs) will still fail.

---

## Side-by-Side Comparison

The `Evaluator.compare_two()` method supports head-to-head comparison of two agents on the same case:

**Judge prompt**: `side_by_side`

```yaml
winner: "A" | "B" | "Tie"
reasoning: "<string>"
better_response_score: <float 0.0-1.0>
```

A statistical p-value is available via `calculate_p_value()` (paired t-test on assertion scores across the full eval set), enabling rigorous significance testing when comparing two agent configurations.

---

## Result Structure

Each evaluation run produces a JSON file under `python/results/`:

```json
{
  "metadata": {
    "tenant": "../examples/tenants/hugesmoothtech-corp-20260404/tenant.yaml",
    "eval_set": "../examples/tenants/hugesmoothtech-corp-20260404/eval_dataset_20260405_0033.yaml",
    "agent_config": "../examples/agents/react_agent.yaml",
    "judge_config": "../examples/evals/default_judge.yaml",
    "eval_set_name": "Evaluation Set for hugesmoothtech-corp-20260404",
    "total_cases": 150,
    "timestamp": "2026-04-06T15:13:23.579600+00:00"
  },
  "summary": {
    "passed": 35,
    "failed": 115,
    "total": 150,
    "pass_rate": 0.2333,
    "mean_assertion_score": 0.5489,
    "mean_citation_score": 0.6097,
    "mean_tool_citation_score": 0.766,
    "mean_response_citation_score": 0.4533,
    "mean_tool_search_result_number": 17.81,
    "mean_tool_search_result_relevance": 0.766,
    "mean_response_citation_number": 2.23,
    "mean_response_citation_relevance": 0.4533
  },
  "cases": [
    {
      "case_id": "case_001",
      "query": "Show me the email from Hyun-Jae Wang...",
      "response": "...",
      "tool_calls": [
        {
          "name": "search_people",
          "arguments": {"query": ["Hyun-Jae Wang"]},
          "result": "..."
        },
        {
          "name": "search_email",
          "arguments": {"query": ["..."]},
          "result": "..."
        }
      ],
      "metrics": {
        "citation_score": 0.85,
        "tool_citation_score": 0.9,
        "response_citation_score": 0.8,
        "tool_search_result_number": 8,
        "tool_search_result_relevance": 0.9,
        "response_citation_number": 1,
        "response_citation_relevance": 0.8,
        "assertion_score": 0.667,
        "latency": 4.23,
        "tool_calls_count": 2,
        "llm_calls_count": 3
      },
      "assertion_results": [
        {"id": 1, "passed": true,  "reasoning": "...", "description": "..."},
        {"id": 2, "passed": true,  "reasoning": "...", "description": "..."},
        {"id": 3, "passed": false, "reasoning": "...", "description": "..."}
      ],
      "reasoning": "Citation: ... | Assertions: ...",
      "passed": false
    }
  ]
}
```

The file is auto-named `eval_{tenant_id}_{YYYYMMDD}_{HHMMSS}.json` when `--output` is not specified.

---

## Sample Results (hugesmoothtech-corp, react_agent)

From `python/results/eval_hugesmoothtech-corp-20260404_20260406_151323.json` (150 cases):

| Metric | Value |
|---|---|
| Pass rate | 23.3% (35/150) |
| Mean assertion score | 0.549 |
| Mean tool citation score | 0.766 |
| Mean response citation score | 0.453 |
| Mean tool search results returned | 17.81 |
| Mean response citations | 2.23 |

The relatively high tool citation score (0.766) vs. lower response citation score (0.453) indicates that the agent retrieves relevant information but frequently fails to format a proper `## References` section—a common failure mode for the base ReAct agent.

---

## Running the Harness

```bash
cd python

# Minimal invocation (auto-detects provider from env vars)
python run_eval.py \
    --tenant  ../examples/tenants/hugesmoothtech-corp-20260404/tenant.yaml \
    --eval    ../examples/tenants/hugesmoothtech-corp-20260404/eval_dataset_20260405_0033.yaml

# Full invocation with explicit paths and Azure override
python run_eval.py \
    --tenant  ../examples/tenants/hugesmoothtech-corp-20260404/tenant.yaml \
    --eval    ../examples/tenants/hugesmoothtech-corp-20260404/eval_dataset_20260405_0033.yaml \
    --agent   ../examples/agents/react_agent_v2.yaml \
    --judge   ../examples/evals/default_judge.yaml \
    --output  results/my_eval.json \
    --provider azure \
    --temperature 0.0
```

Required environment variables (`.env` or shell):
```bash
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://...
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
```

---

## Extending the Harness

### Adding a New Metric

1. Implement the scoring logic in `Evaluator` (either LLM-based or deterministic).
2. Add the score to the `metrics` dict in `evaluate_single()`.
3. Add the aggregation logic in `run_eval.py`'s summary computation.
4. No changes are needed to the result schema; the `metrics` dict is open.

### Using a Different Judge Model

Edit the `model` section of the judge YAML:
```yaml
model:
  provider: openai
  name: gpt-4.1
  parameters:
    temperature: 0.0
```

### Customising Judge Prompts

Replace any prompt under `prompts:` in the judge YAML. The harness looks up prompts by key (`citation_relevance`, `assertion_check`, `response_citation`, `side_by_side`). Missing prompts cause the corresponding sub-score to default to 0.0 with a logged warning.
