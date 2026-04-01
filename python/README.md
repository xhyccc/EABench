# EABench Python — Agent Execution and Evaluation Platform

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)

This directory contains the full Python implementation of **EABench**: a modular, LLM-agnostic platform for executing, testing, and evaluating AI agents in realistic enterprise environments. It covers the complete lifecycle—from synthetic data generation and flexible agent configuration, through secure sandboxed execution, to multi-dimensional evaluation.

---

## Table of Contents

1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Installation](#installation)
4. [Configuration](#configuration)
   - [Environment Variables](#environment-variables)
   - [Agent Configuration (YAML)](#agent-configuration-yaml)
   - [Tenant Configuration](#tenant-configuration)
5. [Quickstart](#quickstart)
   - [Web UI](#web-ui)
   - [CLI Demo](#cli-demo)
6. [Data Generation](#data-generation)
7. [Evaluation](#evaluation)
8. [Agent Strategies](#agent-strategies)
9. [Tools Reference](#tools-reference)
10. [Adding a New Tool](#adding-a-new-tool)
11. [LLM Providers](#llm-providers)
12. [Sandbox Backends](#sandbox-backends)
13. [Developer Workflow](#developer-workflow)
14. [Tests](#tests)

---

## Overview

EABench provides a complete pipeline for building and rigorously evaluating enterprise AI agents:

| Capability | Description |
|---|---|
| **Synthetic data generation** | LLM-driven creation of realistic tenants (users, emails, meetings, files, chats, channels) at arbitrary scale |
| **Configurable agent strategies** | ReAct (interactive loop) and Researcher (Plan-then-Execute) flows, all defined in YAML |
| **Enterprise tool suite** | File I/O, shell execution, Python execution, and semantic search across every content type |
| **Secure sandboxed execution** | Isolated local or Docker sandboxes prevent data exfiltration and destructive commands |
| **Multi-provider LLM support** | OpenAI, Azure OpenAI, Anthropic, and local models via a thin adapter layer |
| **Multi-dimensional evaluation** | Deterministic assertions, LLM-as-a-Judge, citation scoring, and side-by-side comparisons |
| **Interactive web UI** | Streamlit app for chat, batch evaluation, A/B comparison, and on-the-fly tenant generation |

---

## Directory Structure

```
python/
├── app.py                  # Streamlit web UI (chat, eval, A/B compare, data gen)
├── main.py                 # CLI entry point: single-query agent demo
├── generate_data.py        # CLI: generate a synthetic tenant (data + embeddings)
├── generate_eval.py        # CLI: generate an evaluation dataset for an existing tenant
├── debug_search.py         # CLI: interactive search engine debugging utility
├── conftest.py             # Pytest fixtures and shared test configuration
├── install.sh              # One-step install script (creates .venv)
├── requirements.txt        # Python dependencies
│
├── src/
│   ├── config/
│   │   ├── agent_config.py     # Pydantic schema for AgentConfig (model, tools, flow, prompts)
│   │   └── tenant_config.py    # Pydantic schema for TenantConfig (users, emails, meetings, …)
│   │
│   ├── core/
│   │   ├── agent_runner.py     # Main orchestration: ReAct loop & Researcher strategy
│   │   ├── llm_provider.py     # Abstract LLMProvider interface + Message/ToolCall models
│   │   ├── openai_provider.py  # OpenAI API adapter
│   │   ├── azure_provider.py   # Azure OpenAI API adapter
│   │   ├── embedding_provider.py  # Embedding adapters (Azure, local, mock)
│   │   ├── tool_registry.py    # ToolRegistry + @registry.register decorator
│   │   ├── tools.py            # All built-in tools (file, search, execute)
│   │   ├── search_engine.py    # Vector-based semantic search with user-context filtering
│   │   ├── query_analyzer.py   # LLM-powered per-query search strategy selection
│   │   └── logger.py           # Debug logger for reasoning traces and tool execution
│   │
│   ├── eval/
│   │   ├── evaluator.py        # Evaluation engine: assertions, citation scoring, LLM Judge
│   │   └── models.py           # EvaluationCase, EvaluationResult, ComparisonResult
│   │
│   ├── generator/
│   │   ├── pipeline.py         # DataGenerator: batched generation of users, emails, meetings, files
│   │   └── models.py           # StoryConfig, GenerationOutput
│   │
│   └── sandbox/
│       ├── base.py             # Abstract SandboxInterface (read, write, list, execute)
│       └── local_sandbox.py    # LocalSandbox: temp-dir isolation + subprocess execution
│
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_eval_parsing.py
    ├── test_evaluator.py
    ├── test_llm_provider.py
    ├── test_sandbox.py
    ├── test_search_engine.py
    └── test_tools.py
```

---

## Installation

```bash
# From the python/ directory
bash install.sh          # production install (creates .venv)
bash install.sh --dev    # also installs pytest, black, ruff

source .venv/bin/activate
```

The install script creates an isolated virtual environment and installs all dependencies from `requirements.txt`.

**Key dependencies:** `pydantic`, `pyyaml`, `openai`, `sentence-transformers`, `streamlit`, `docker`, `scipy`, `scikit-learn`, `opentelemetry-api`.

---

## Configuration

### Environment Variables

Create a `.env` file in the **repository root** (never commit it):

```dotenv
# Azure OpenAI
AZURE_API_KEY=<your-key>
AZURE_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_API_VERSION=2024-02-15-preview

# OpenAI
OPENAI_API_KEY=<your-key>
OPENAI_API_BASE=https://api.openai.com/v1   # optional override
```

### Agent Configuration (YAML)

Agent configs live in `examples/agents/`. Each YAML file fully describes one agent:

```yaml
id: react_agent_v1
version: "1.0"

model:
  provider: azure          # openai | azure | anthropic | local
  name: gpt-4o
  parameters:
    temperature: 0.0

embedding:
  provider: azure
  model: text-embedding-3-small

system_prompt: |
  You are a helpful enterprise assistant. Answer questions using the tools
  provided. Always cite your sources using [^N^] notation.
  {user_profile}

tools:
  definitions:
    - read_file
    - list_files
    - search_email
    - search_file
    - search_meeting
    - search_chat
    - search_people

flow:
  strategy: react          # react | researcher
  max_turns: 15
```

**`flow.strategy` options:**

| Strategy | Behaviour |
|---|---|
| `react` | Classic Reason → Act → Observe loop until a final answer is produced |
| `researcher` | Generates a step-by-step plan first, then executes it via the ReAct loop |

### Tenant Configuration

Tenants live in `examples/tenants/<tenant-id>/`. A tenant directory contains:

```
tenant-id/
├── tenant.yaml        # Users, resource limits, references to sub-files
├── emails.yaml        # Email corpus
├── meetings.yaml      # Meeting records (agenda + transcript)
├── chats.yaml         # 1-on-1 chats
├── group_chats.yaml   # Group chat threads
├── channels.yaml      # Slack-like channels
├── files/             # Files accessible to the agent
└── .cache/            # Auto-generated embedding cache (gitignored)
```

The minimal `tenant.yaml` structure:

```yaml
id: my-tenant
users:
  - id: user_001
    username: alice@example.com
    groups: [engineering]
    profile:
      email: alice@example.com
      name:
        display_name: Alice Smith
        first_name: Alice
        last_name: Smith
      department: Engineering
      title: Software Engineer

resource_limits:
  max_file_size_kb: 1024
  max_files: 100
```

---

## Quickstart

### Web UI

```bash
cd python
python -m streamlit run app.py
# Open http://localhost:8501
```

The web UI offers four modes accessible from the sidebar:

| Mode | Description |
|---|---|
| **Chat** | Send queries to the agent; inspect reasoning traces and tool calls in real time |
| **Evaluation** | Run a full evaluation dataset against an agent and view pass/fail results |
| **Side-by-Side** | Compare two agent configs on the same query set with LLM-based winner detection |
| **Data Generator** | Create new tenants interactively without using the CLI |

Switch tenants and users from the sidebar to change the agent's data scope.

### CLI Demo

```bash
cd python
python main.py
```

This runs a pre-configured single query against the default tenant and prints the agent response plus execution metrics.

---

## Data Generation

Generate a fully synthetic enterprise tenant with a single command:

```bash
python generate_data.py \
  --company "Acme Corp" \
  --industry "SaaS" \
  --size small \
  --num_users 10 \
  --days 14 \
  --eval_batch_size 5 \
  --events "Project Alpha Kickoff" "Production Outage" \
  --description "Incident response training scenario" \
  --prompts examples/generation/default_prompts.yaml
```

**Output layout:**

```
examples/tenants/acme-corp-<date>/
├── tenant.yaml
├── emails.yaml
├── meetings.yaml
├── chats.yaml
├── group_chats.yaml
├── channels.yaml
└── files/
```

The generator uses an LLM to produce coherent, inter-connected narratives across all content types: emails reference meeting action items, files document project status, chats discuss incidents, and so on.

**Key parameters:**

| Parameter | Description |
|---|---|
| `--company` | Company name (used in generated content) |
| `--industry` | Industry vertical (e.g., SaaS, Healthcare, Finance) |
| `--size` | `small`, `medium`, or `large` (affects content volume) |
| `--num_users` | Number of synthetic employees |
| `--days` | Simulated timeline length in days |
| `--events` | Named events that drive the story arc (e.g., product launches, incidents) |
| `--description` | Free-text scenario description fed directly to the LLM |
| `--prompts` | Path to the generation prompt templates YAML |

---

## Evaluation

### Generate an Evaluation Dataset

```bash
python generate_eval.py \
  --tenant_path examples/tenants/acme-corp-20251230 \
  --num_queries 50 \
  --batch_size 10 \
  --prompts examples/generation/default_prompts.yaml
```

Produces `eval_dataset_<timestamp>.yaml` inside the tenant directory.

### Evaluation Dataset Format

```yaml
name: Acme Corp Evaluation Set
description: Tests covering incident response and project tracking
cases:
  - id: case_001
    query: "Summarize action items from the production outage meeting."
    user_id: user_001
    assertions:
      - description: "Response mentions at least one action item owner"
    entity_list: []

  - id: case_002
    query: "Find all emails from Alice about Project Alpha."
    user_id: user_002
    assertions:
      - description: "Response references emails from alice@example.com"
```

### Running Evaluation via the Web UI

1. Open the web UI and switch to **Evaluation** mode.
2. Select an agent config and a tenant.
3. Pick an evaluation dataset YAML file.
4. Click **Run Evaluation** and inspect per-case results.

### Evaluation Metrics

| Metric | Description |
|---|---|
| **Assertion score** | Fraction of LLM-graded assertions that pass (0–1) |
| **Citation score** | Relevance of `[^N^]` citations verified against source entities |
| **Latency** | Wall-clock time for the agent to produce a response |
| **Tool call count** | Total number of tool invocations |
| **Token usage** | Prompt and completion tokens per LLM call |

A case **passes** when `assertion_score ≥ 0.75` AND `citation_score ≥ 0.70`. Both thresholds are defaults defined in `evaluator.py` and can be adjusted for stricter or more lenient evaluation regimes.

---

## Agent Strategies

### ReAct

The default strategy. The agent iterates through Reason → Act → Observe cycles until it produces a final answer or reaches `max_turns`.

```
User query
    │
    ▼
┌─────────────────────────────────┐
│  System prompt + user profile   │
│  + conversation history + tools │
└────────────────┬────────────────┘
                 │
         ┌───────▼──────┐
         │   LLM call   │◄────────────────┐
         └───────┬──────┘                 │
                 │                        │
      ┌──────────▼──────────┐             │
      │   Tool call(s)?     │             │
      └──────────┬──────────┘             │
                 │ yes                    │
         ┌───────▼──────┐                 │
         │  Execute in  ├─── result ──────┘
         │   sandbox    │
         └──────────────┘
                 │ no (final answer)
                 ▼
            Response
```

### Researcher (Plan-then-Execute)

Generates a high-level research plan first, then feeds it into the ReAct loop. Useful for complex multi-hop queries where explicit step decomposition improves accuracy and reduces unnecessary tool calls.

```
User query
    │
    ▼
┌─────────────────────────────────┐
│  Planning LLM call (no tools)   │
└────────────────┬────────────────┘
                 │ plan
                 ▼
        ReAct loop (with plan
        injected as context)
                 │
                 ▼
           Final answer
       (planning artifacts
          stripped out)
```

Configure via `flow.strategy: researcher` in the agent YAML. Customise the planning prompt with `planning_prompt` in the same file.

---

## Tools Reference

All tools are registered with `@registry.register` and automatically exposed to the LLM as JSON schemas.

| Tool | Description |
|---|---|
| `read_file` | Read the content of a file from the sandbox |
| `list_files` | List files and directories at a path |
| `execute_command` | Run an arbitrary shell command (sandboxed) |
| `execute_python` | Execute Python code, capture stdout/stderr and new files |
| `search_email` | Semantic + keyword search across email corpus, with sender/date filtering |
| `search_file` | Semantic search over files indexed in the tenant |
| `search_chat` | Search 1-on-1 chat messages |
| `search_group_chat` | Search group chat threads |
| `search_channel` | Search Slack-like channel posts |
| `search_meeting` | Search meeting agendas and transcripts |
| `search_people` | Search the user directory by name, title, skill, or department |
| `search_in_file` | Keyword search within a specific file |

Enable or disable tools per-agent via the `tools.definitions` list in the agent YAML.

---

## Adding a New Tool

1. Define an input schema using Pydantic:

```python
from pydantic import BaseModel, Field
from .tool_registry import registry

class MyToolInput(BaseModel):
    param: str = Field(..., description="Description shown to the LLM")
```

2. Implement and register the tool:

```python
@registry.register(name="my_tool", args_schema=MyToolInput)
def my_tool(param: str, sandbox: SandboxInterface) -> str:
    """Short docstring used as the tool description for the LLM."""
    return sandbox.read_file(param)
```

3. Add `my_tool` to `tools.definitions` in an agent YAML.

Dependencies (`sandbox`, `search_engine`, `llm`, `query_analyzer`) are injected automatically by `AgentRunner._execute_tool` if present in the function signature.

---

## LLM Providers

| Provider | Class | Config `provider` value |
|---|---|---|
| OpenAI | `OpenAIProvider` | `openai` |
| Azure OpenAI | `AzureProvider` | `azure` |
| Mock (testing) | `MockLLMProvider` | — |

All providers implement the `LLMProvider` abstract interface:

```python
class LLMProvider:
    async def generate(self, messages: List[Message], tools: List[dict]) -> Message: ...
    async def get_completion(self, messages: List[dict]) -> str: ...
```

To add a new provider, subclass `LLMProvider`, implement `generate` and `get_completion`, and instantiate it before creating `AgentRunner`.

---

## Sandbox Backends

| Backend | Class | Use case |
|---|---|---|
| Local (temp dir) | `LocalSandbox` | Development and CI |
| Docker | *(planned)* | Untrusted agent code, production isolation |
| gVisor/Kata | *(planned)* | Highest security requirements |

`LocalSandbox` creates a temporary directory, copies tenant files into it, and restricts all file operations to that directory. Shell commands run via `subprocess` with a configurable timeout.

---

## Developer Workflow

```bash
# Install development dependencies
bash install.sh --dev
source .venv/bin/activate

# Run tests
pytest tests/ -q

# Lint and format
black . && ruff .

# Run a single agent from the CLI
python -m src.core.agent_runner \
  --agent examples/agents/researcher_agent.yaml \
  --tenant examples/tenants/test-tenant-1

# Debug search engine interactively
python debug_search.py \
  --tenant examples/tenants/test-tenant-1 \
  --user user_001
```

---

## Tests

The test suite lives in `tests/` and covers all major components:

| Test file | Coverage |
|---|---|
| `test_config.py` | AgentConfig and TenantConfig YAML loading and validation |
| `test_sandbox.py` | LocalSandbox read, write, list, execute, and path traversal |
| `test_tools.py` | All registered tools with mock sandbox and search engine |
| `test_search_engine.py` | Vector indexing, semantic queries, and user-context filtering |
| `test_evaluator.py` | Assertion scoring, citation scoring, and comparison logic |
| `test_llm_provider.py` | LLMProvider message/tool-call serialization and mock responses |
| `test_eval_parsing.py` | YAML/JSON response parsing in the evaluator |

Run the full suite:

```bash
pytest tests/ -q
```

Run a specific file:

```bash
pytest tests/test_evaluator.py -v
```
