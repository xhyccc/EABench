# Data Generation Pipeline

## Overview

EABench's data generation pipeline produces a fully synthetic enterprise **tenant**—a self-consistent digital universe populated with users, communications, and files—from a short textual story and a list of milestone events. The pipeline is implemented in both Rust (`rust/src/generator/`) and Python (`python/src/generator/`) with identical semantics; the Rust version is preferred for production use because of its performance and reliability.

---

## Inputs

### `StoryConfig`
The pipeline accepts a single configuration object (`StoryConfig`) that describes the synthetic company:

| Field | Type | Description |
|---|---|---|
| `company_name` | string | Used as tenant ID prefix and in prompts |
| `industry` | string | Industry vertical (e.g., "Software", "Finance") |
| `company_size` | string | `"small"` / `"medium"` / `"large"` |
| `num_users` | int | Number of synthetic employees to generate |
| `duration_days` | int | Number of working days to simulate |
| `eval_batch_size` | int | Batch size for LLM calls during user and eval generation |
| `key_events` | list[string] | High-level milestone events that drive the narrative arc |
| `description` | string | Free-text scenario description given to the LLM |

Example key events for a software company:
```
- "Q1 product launch goes live but faces critical bugs"
- "Engineering layoffs are announced"
- "Major enterprise client threatens to leave"
```

---

## Pipeline Stages

### Stage 1 — Directory Scaffold

`DataGenerator.generate_tenant(story)` creates the following on-disk structure:

```
examples/tenants/{company_name}-{YYYYMMDD}/
├── tenant.yaml              # User roster + org structure
├── generation_log.json      # Full event log (input for eval generation)
├── config/
│   ├── emails.yaml
│   ├── chats.yaml
│   ├── group_chats.yaml
│   ├── meetings.yaml
│   └── files.yaml
└── data/                    # Actual file contents (Markdown, text, code)
    └── docs/
        └── ...
```

Each `config/*.yaml` file starts as `[]` and is **incrementally appended** during simulation; this avoids loading the entire dataset into memory.

---

### Stage 2 — User Generation

Users are generated in batches to encourage organisational diversity. The first batch receives the instruction:

> "Focus on creating the core leadership team (C-level) and heads of key departments."

Subsequent batches receive a *diversity context* that includes the current department distribution and the names of the last 10 generated users. The LLM is instructed to fill gaps and avoid name duplication.

**Prompt template**: `generate_users`  
**Key LLM outputs per user**:
- `id` / `username` (unique email alias, e.g. `hwang`)
- `name.display_name`, `first_name`, `last_name`
- `title`, `department`, `manager_id`
- `skills`, `location`, `timezone`
- `groups` (e.g. `["Engineering", "All Employees"]`)

The pipeline enforces uniqueness by tracking generated IDs in a `HashSet` and appending a suffix when a collision occurs.

The resulting `TenantConfig` (user roster only) is serialised to `tenant.yaml` before daily simulation begins.

---

### Stage 3 — Daily Simulation Loop

The pipeline iterates over each simulated day from `start_date` to `start_date + duration_days`.

#### 3a. History Management

Two rolling history buffers prevent the LLM from losing context over long simulations:

| Buffer | Scope | Reset |
|---|---|---|
| `recent_history` | Last ≤7 days, verbatim event entries | Cleared every 7 days |
| `long_history` | Compressed weekly summaries | Accumulates for the full run |

Every 7 days the pipeline calls the `summarize_history` prompt to condense `recent_history` into a paragraph and appends it to `long_history`.

#### 3b. Daily Story Generation

**Prompt**: `generate_daily_story`  
**Context injected**: `company_name`, `description`, `date`, `key_events`, `long_history`, `recent_history`

The LLM returns a JSON list of 3–5 specific narrative events for that day:
```json
{
  "daily_events": [
    "CEO announced a strategic partnership with TechCorp.",
    "Engineering team faced a production incident in the login service.",
    "Marketing started planning the summer campaign."
  ]
}
```

These events are appended to `recent_history` and logged to `generation_log.json`.

#### 3c. Email Generation (Two-Step)

**Step 1 — Summaries** (`generate_email_summaries`):  
The LLM receives today's events and returns a list of email metadata stubs:
```json
[
  {
    "id": "email_004",
    "from_user": "hwang",
    "to_users": ["tsato", "jhassan"],
    "cc_users": ["tkobayashi", "rprasad"],
    "subject": "Technical Feedback on Debugging Update",
    "context_summary": "...",
    "timestamp": "2026-03-25T12:30:00Z"
  }
]
```

**Step 2 — Full Content** (`generate_email_content`):  
For each stub, the LLM generates a realistic email body. Instructions include:
- Minor typos or informal language
- References to prior discussions
- Occasional "Sent from my iPhone" signatures
- Natural human uncertainty ("Can we double-check?")

The constructed `Email` object is immediately appended to `config/emails.yaml` and logged.

#### 3d. Chat Generation (Two-Step)

Follows the same two-step pattern:
1. `generate_chat_summaries` → list of conversation stubs (`type: "chat"` or `"group_chat"`, participants, context)
2. `generate_chat_content` → message-by-message exchange with sequential timestamps

For 1:1 chats (`len(participants) == 2`), the `to_user` field is inferred automatically. The result is appended to `chats.yaml` or `group_chats.yaml` accordingly.

#### 3e. Meeting Generation (Three-Step)

1. `generate_meeting_summaries` → list with `title`, `organizer_id`, `attendee_ids`, `start_time`, `end_time`, `agenda`, `context_summary`
2. `generate_meeting_transcript` → full dialogue with speaker names, interruptions, tangents, action items
3. `generate_meeting_chat` → sidebar chat log that ran in parallel to the meeting

The `Meeting` object bundles all three artefacts and is appended to `meetings.yaml`.

#### 3f. File Generation (Two-Step)

1. `generate_file_summaries` → list of `{path, created_by, context_summary, snippet}` (path must start with `data/`)
2. `generate_file_content` → full Markdown content (reports, specs, code files)

The file content is written directly to the sandbox filesystem under `data/…`, and a `FileMetadata` record (path + snippet) is appended to `config/files.yaml`. Up to three retries are attempted for content generation.

---

### Stage 4 — Generation Log

After the daily loop, all generation events are serialised to `generation_log.json`:

```json
[
  {"date": "2026-03-25", "type": "storyline", "events": [...]},
  {"date": "2026-03-25", "type": "email",   "id": "email_004", "subject": "...", "from": "hwang", "body": "..."},
  {"date": "2026-03-25", "type": "meeting", "id": "meeting_002", "title": "...", "transcript": "..."},
  ...
]
```

This log is the primary input for the **evaluation dataset generation** pipeline (Stage 5 in the overall flow).

---

## Prompt Infrastructure

All prompt templates are stored in a single YAML file (default: `examples/generation/default_prompts.yaml`). Each key maps to a string template with `{placeholder}` variables. The pipeline loads them at startup:

```yaml
model_config:
  provider: azure
  model: gpt-4o
  temperature: 0.7

generate_users: |
  You are a data generator for an enterprise simulation.
  ...

generate_daily_story: |
  ...
```

Template substitution uses `format_template()` (Rust) / Python's `.format()`, which also escapes JSON-embedded curly braces (`{{` → `{`).

---

## LLM Provider Abstraction

The pipeline is provider-agnostic via the `LLMProvider` trait (Rust) / abstract class (Python):

```
LLMProvider
├── OpenAIProvider      (direct API)
├── AzureOpenAIProvider (Azure-hosted)
└── MockLLMProvider     (unit testing)
```

Both synchronous (Rust) and asynchronous (Python `async/await`) interfaces are supported. JSON responses from the LLM are parsed defensively: the parser strips Markdown code fences, tries direct JSON parsing, then falls back to bracket-scanning to extract a valid JSON object or array.

---

## Output Summary

After a successful run, `generate_tenant()` returns:

```rust
GenerationOutput {
    tenant_id: "hugesmoothtech-corp-20260404",
    base_path: "examples/tenants/hugesmoothtech-corp-20260404",
    summary: "Generated tenant hugesmoothtech-corp-20260404 with users and content."
}
```

The directory is immediately ready to be ingested by the evaluation harness or inspected manually.
