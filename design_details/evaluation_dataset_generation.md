# Evaluation Dataset Generation Pipeline

## Overview

The evaluation dataset generation pipeline transforms the raw output of the data generation pipeline—specifically the `generation_log.json` artefact and the user roster—into a structured set of **evaluation cases** (`eval_dataset_*.yaml`). Each case contains a natural-language query, a `user_id` acting as the query originator, a list of checkable assertions, and an optional entity list of ground-truth artefacts.

The pipeline is implemented in `python/src/generator/pipeline.py` (`generate_eval_dataset`) and driven by the prompts in `examples/generation/default_prompts.yaml`.

---

## Inputs

| Input | Description |
|---|---|
| `generation_log.json` | Full event log produced by the data generation stage |
| `tenant.yaml` | User roster (used to build `users_context`) |
| `num_queries` | Total target number of evaluation cases (default: 200) |
| `batch_size` | Number of artefacts processed per LLM call (default: 10) |

---

## Query Type Distribution

The pipeline produces three categories of evaluation cases in a fixed ratio:

| Type | Target Share | Nature |
|---|---|---|
| **Search / Needle-in-a-Haystack** | ~40% | Find a specific artefact or small set of artefacts |
| **Multi-hop Reasoning** | ~40% | Trace a chain of dependencies across multiple data sources |
| **Report Generation** | ~20% | Synthesise a topic summary from many artefacts over a time window |

---

## Stage 1 — Search Query Generation

**Prompt**: `generate_search_eval`

The pipeline shuffles all artefacts (emails, meetings, files, chats) and processes them in batches of `batch_size`. For each batch, a context summary is built:

```json
[
  {
    "id": "email_004",
    "type": "email",
    "date": "2026-03-25",
    "summary": "Hyun-Jae provides feedback on debugging update",
    "from": "hwang",
    "subject": "Technical Feedback on Debugging Update"
  },
  {
    "id": "meeting_002",
    "type": "meeting",
    "date": "2026-03-25",
    "title": "Sprint Review",
    "attendees": ["hwang", "tsato"]
  }
]
```

The LLM is instructed to generate **needle-in-a-haystack** queries: natural language questions that implicitly constrain the result to a specific item (by time, author, type, or keywords) without mentioning IDs directly.

**Example LLM output**:
```json
[
  {
    "reasoning": "hwang sent a technical feedback email on March 25. A realistic query from a recipient.",
    "query": "Show me the email from Hyun-Jae Wang about the engineering team's feedback on debugging improvements sent on March 25th.",
    "user_id": "tsato",
    "assertions": [
      "Returns the email 'Technical Feedback on Debugging Update' from hwang",
      "Identifies the date as March 25, 2026",
      "Contains at least one of the issues raised (false positives, integration lag, user feedback)"
    ],
    "entity_list": [
      {"entity_type": "email", "entity_id": "email_004"}
    ]
  }
]
```

Generation continues until `num_search` (40% of total) cases are collected.

---

## Stage 2 — Multi-hop Query Generation

**Prompt**: `generate_multihop_eval`

The pipeline groups all non-storyline events by date and processes each day's cluster. A day is skipped if it has fewer than two events (multi-hop requires at least two linked artefacts).

The context per batch is a list of event summaries for a single day:
```json
[
  {"id": "email_003", "type": "email",   "summary": "CEO announces partnership"},
  {"id": "meeting_001", "type": "meeting", "summary": "Emergency product sync"},
  {"id": "file_007",  "type": "file",   "summary": "Q1 strategy document updated"}
]
```

The LLM is instructed to generate queries that **require two or more retrieval steps** to answer. The canonical example:

> "Who was the organiser of the meeting discussed in Sarah's email about 'Budget'?"

This requires:
1. Finding Sarah's email about Budget → extract the meeting reference
2. Looking up that meeting → extract the organiser

**Key prompt constraints**:
- Each query must have `assertions` describing what a correct answer must contain
- Each query must have an `entity_list` listing the specific artefacts that would be needed
- A realistic `user_id` is assigned to each query

Each generated case is tagged with `"type": "multihop"` before being appended to the dataset.

---

## Stage 3 — Report Generation Query Generation

**Prompt**: `generate_report_eval`

Report queries ask the agent to synthesise a coherent narrative or analysis from multiple artefacts spread over a time window of 3–7 days.

The pipeline:
1. Sorts storyline entries by date
2. Randomly picks a window (`random.randint(3, 7)` days)
3. Gathers all artefacts (emails, meetings, files, chats) in that window
4. Builds a rich context combining narrative events and artefact summaries

```
Storyline: [2026-03-24] Engineering team faces production incident
           [2026-03-25] Debugging hotfix deployed; client escalates
           [2026-03-26] Rollback discussion begins
Artifacts:
- email_004: "Technical Feedback on Debugging Update" (hwang, 2026-03-25)
- file_003: data/reports/incident_report.md (rprasad, 2026-03-26)
- meeting_002: "Emergency Response Sync" (tsato, 2026-03-25)
```

The LLM produces queries such as:

> "Write a briefing on the server crash incident, including the timeline and root cause."

**Assertions** must reference the window artefacts specifically:
- "Mentions the production incident on March 24"
- "Identifies the hotfix deployed by the AI team"
- "References the rollback discussion from the incident report"

---

## Output Format

All three query types are merged into a single `eval_dataset_*.yaml` file per tenant:

```yaml
- id: case_001
  query: "Show me the email from Hyun-Jae Wang about the engineering team's feedback..."
  user_id: tsato
  assertions:
    - description: "Returns the email 'Technical Feedback on Debugging Update' from hwang"
      weight: 1.0
    - description: "Identifies the date as March 25, 2026"
      weight: 1.0
  expected_tools: null

- id: case_045
  query: "Who organised the meeting that was discussed in the email about the Q1 budget?"
  user_id: snguyen
  assertions:
    - description: "Identifies the Q1 budget email"
    - description: "Extracts the meeting reference from that email"
    - description: "Returns the organiser's name"
  expected_tools: null
```

The file is named `eval_dataset_{YYYYMMDD}_{HHMMSS}.yaml` and placed in the tenant directory.

---

## Ground Truth Design Principles

### Assertions vs. Expected Entities

Each evaluation case carries two forms of ground truth:

- **Assertions** (natural language, LLM-checked): Describe *what* the answer must contain. Used by the LLM-as-Judge assertion checker during evaluation.
- **entity_list** (structured IDs): The specific artefacts the agent should retrieve. Used for diagnostic tracing and could support future exact-match metrics.

### Realism Constraints in Prompts

The prompts enforce several constraints to improve query realism:
- Queries must *not* mention IDs explicitly
- Users are drawn from the actual tenant roster and assigned realistically (e.g., a recipient of an email, an attendee of a meeting)
- Multi-hop chains must be achievable from the artefacts provided in context

### Coverage and Diversity

- The **40 / 40 / 20** split ensures that retrieval precision (search), reasoning depth (multi-hop), and synthesis quality (report) are all exercised
- Randomised shuffling and windowing prevent spatial bias toward earlier events in the simulation

---

## Running the Pipeline

```bash
# Generate eval dataset for an existing tenant
python python/generate_eval.py \
  --tenant_path examples/tenants/hugesmoothtech-corp-20260404 \
  --num_queries 200 \
  --batch_size 10 \
  --prompts examples/generation/default_prompts.yaml
```

The script reads the LLM provider configuration from `default_prompts.yaml`'s `model_config` section and supports both OpenAI and Azure OpenAI backends via environment variables (`OPENAI_API_KEY` / `AZURE_OPENAI_API_KEY`, etc.).
