# EABench - Agent Execution and Evaluation Platform

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/) [![Rust](https://img.shields.io/badge/rust-1.75%2B-orange.svg)](https://www.rust-lang.org/)

EABench is a modular platform to execute, test, and evaluate LLM-powered agents in hermetic sandboxes. It provides realistic synthetic tenant data (emails, chats, meetings, files), configurable agent workflows, secure tool execution, and an evaluation framework combining deterministic assertions with LLM-based judging.

**Architecture**: The **Rust CLI** handles offline data generation and evaluation. The **Python Streamlit web UI** is the interactive front-end for chatting with agents, running evaluations, and generating new datasets.

---

## Highlights ✅

- **Rust CLI for data generation**: Fast, parallel tenant generation with `eabench generate`. Supports Azure OpenAI and OpenAI-compatible providers.
- **Streamlit Web UI**: Four views — Chat, Evaluation, Side-by-Side Comparison, and Data Generator — all in the browser.
- **Sandboxed Execution**: Agents run in isolated local sandboxes with read/write/execute tool access.
- **Multi-Provider LLM Support**: Azure OpenAI, OpenAI-compatible endpoints (SiliconFlow, etc.), or local LLMs.
- **Embeddings & Caching**: Azure or local `sentence-transformers` embeddings, cached per-tenant as `.cache/*.pkl`.
- **Flexible Agent Strategies**: ReAct (interactive loop) and Researcher (Plan-then-Execute).
- **LLM-as-a-Judge Evaluation**: Deterministic assertions + configurable judge prompts for qualitative scoring.

---

## Quickstart 🚀

### 1. Prerequisites

```bash
git clone https://github.com/your-org/EABench.git
cd EABench
```

Create a `.env` file in the repo root (never commit it):

```env
# Azure OpenAI
AZURE_API_KEY=<your-key>
AZURE_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
AZURE_API_VERSION=2024-12-01-preview
AZURE_EMB_API_VERSION=2023-05-15

# OpenAI-compatible (optional)
OPENAI_API_KEY=<your-key>
OPENAI_API_BASE=https://api.siliconflow.cn/v1
OPENAI_MODEL=Qwen/Qwen3-32B
```

### 2. Build the Rust CLI

```bash
# From repo root
cargo build --release --manifest-path rust/Cargo.toml
# Binary at: rust/target/release/eabench
```

### 3. Set up Python (web UI)

```bash
# From repo root
python3 -m venv .venv
.venv/bin/pip install -r python/requirements.txt
```

### 4. Generate a tenant (Rust CLI)

```bash
# From repo root
set -a && source .env && set +a

# Small tenant (Azure)
./rust/target/release/eabench generate \
  --company "Acme Corp" \
  --industry "Technology" \
  --description "A software startup building a SaaS product" \
  --events "Project Kickoff" "Q1 Review" \
  --size small \
  --num-users 5 \
  --days 7 \
  --provider azure

# Large tenant with many events (Azure)
./rust/target/release/eabench generate \
  --company "HugeSmoothTech Corp" \
  --industry "Software Technology" \
  --description "A software giant building SaaS products" \
  --events "Project Kickoff" "Q1 Review" "Performance Review" "Sales Layoff" \
           "SDE Reorganization" "Product Refocus" "AI and LLM replacements" \
           "Use coding agents to replace SDE" "SDE layoff" \
  --size large \
  --num-users 40 \
  --days 100 \
  --provider azure
```

Output is written to `examples/tenants/<company-slug-YYYYMMDD>/`.

### 5. Launch the web UI

```bash
# From repo root
set -a && source .env && set +a

# Option A: directly
.venv/bin/streamlit run python/app.py --server.port 8501

# Option B: via the Rust binary
./rust/target/release/eabench serve
```

Open **http://localhost:8501**, select a tenant and user from the sidebar, and start chatting.

---

## Python Web UI

The Streamlit app (`python/app.py`) is the primary interactive interface. Launch it with:

```bash
# From repo root
set -a && source .env && set +a
.venv/bin/streamlit run python/app.py --server.port 8501
```

The sidebar lets you pick a **tenant**, a **user identity**, and an **agent config**. It has four views:

### Chat
Send a natural-language query and receive a grounded agent response. The agent uses the selected strategy (ReAct or Researcher) and can call tools (file read/write, shell execution, semantic search). After each turn, two debug expanders are shown:
- **Reasoning Trace** — every LLM call and response in the turn
- **Search Analysis** — each tool invocation with query-analyzer output and raw results

### Evaluation
Upload or select an eval dataset YAML, choose an agent config, and run the full evaluation suite. Per-case results are displayed with pass/fail for each assertion and the LLM judge score. A summary table is shown at the end.

### Side-by-Side Comparison
Run the same eval dataset against two different agent configs simultaneously to compare responses, tool usage, and scores in a unified table. Results can be downloaded as YAML.

### Data Generator
Generate a new synthetic tenant entirely from within the browser. Fill in company name, industry, description, events, size, user count, days, and LLM provider, then click **Generate**. Progress is streamed live; the new tenant appears immediately in the tenant selector.

---

## Rust CLI

The Rust binary (`rust/target/release/eabench`) handles offline data generation and evaluation. All commands below are run from the **repo root** after loading credentials:

```bash
set -a && source .env && set +a
```

### `generate` — Create a synthetic tenant

Drives an LLM to produce a full set of users, emails, chats, meetings, channel posts, files, and an evaluation dataset, all written as YAML under `examples/tenants/<slug>/`.

```bash
./rust/target/release/eabench generate \
  --company    "Acme Corp" \
  --industry   "Technology" \
  --description "A software startup" \
  --events     "Project Kickoff" "Q1 Review" \
  --size       small \
  --num-users  5 \
  --days       7 \
  --provider   azure
```

Optional flags:
- `--output <dir>` — output directory (default: `examples/tenants`)
- `--prompts <path>` — prompt templates YAML (default: `examples/generation/default_prompts.yaml`)
- `--model <name>` — override deployment/model name
- `--dry-run` — validate config without calling the LLM

Generated tenant layout:
```
examples/tenants/<slug>/
├── tenant.yaml           # Users and basic tenant metadata
├── config/
│   ├── emails.yaml       # Generated emails
│   ├── chats.yaml        # 1-on-1 chats
│   ├── group_chats.yaml  # Group chats
│   ├── meetings.yaml     # Meetings with transcripts
│   └── files.yaml        # File metadata
├── data/                 # Actual file contents
├── docs/                 # Additional documents
└── eval_dataset_<ts>.yaml  # Auto-generated evaluation dataset
```

### `eval` — Run deterministic evaluation

Runs an eval dataset against a tenant, executing each query through the agent and scoring assertions without human involvement.

```bash
./rust/target/release/eabench eval \
  --tenant  examples/tenants/hugesmoothtech-corp-20260404/tenant.yaml \
  --eval    examples/tenants/hugesmoothtech-corp-20260404/eval_dataset_20260405_0033.yaml \
  --workers 4
```

### `serve` — Launch the web UI

```bash
./rust/target/release/eabench serve              # default port 8501
./rust/target/release/eabench serve --port 8502  # custom port
```

Looks for `.venv/bin/streamlit` in the repo root first, then falls back to `streamlit` on PATH.

---

## YAML Data Format

All tenant content (emails, chats, meetings, etc.) is stored as YAML lists. Multi-line string values such as email bodies and meeting transcripts are always written as inline double-quoted scalars with `\n` escape sequences:

```yaml
- id: email_001
  from_user: ajackson
  subject: "Follow-Up on Employee Support Memo"
  body: "Hi Devanshi,\n\nHope you're well.\n\nBest,\nAmara"
  timestamp: "2026-03-25T09:00:00Z"
  to_users: [dpatel, knguyen]
```

This format is consistent regardless of what the LLM returns, and round-trips correctly through `yaml.safe_load` and `serde_yaml`.

---

## Configuration

### Environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `AZURE_API_KEY` | Azure OpenAI API key |
| `AZURE_ENDPOINT` | Azure OpenAI endpoint URL |
| `AZURE_API_VERSION` | Chat completions API version (e.g. `2024-12-01-preview`) |
| `AZURE_EMB_API_VERSION` | Embeddings API version (e.g. `2023-05-15`) |
| `OPENAI_API_KEY` | OpenAI / compatible API key |
| `OPENAI_API_BASE` | Custom base URL (e.g. SiliconFlow) |
| `OPENAI_MODEL` | Model name for OpenAI provider |

### Agent configs

Agent configs live in `examples/agents/`. Key fields:
- `model`: provider (`azure` or `openai`), deployment name, temperature
- `embedding`: provider and model for semantic search
- `flow.strategy`: `react` or `researcher`
- `tools.definitions`: list of enabled tool names
- `query_analyzer_prompt`: per-domain LLM prompts that refine search queries

### Tenant data

Tenants live under `examples/tenants/<tenant-id>/`:
- `tenant.yaml` — users and basic metadata
- `config/*.yaml` — emails, chats, meetings, group chats
- `data/` — actual file contents
- `docs/` — additional documents
- `.cache/` — precomputed embeddings cache (delete to force re-index)

---

## Important Concepts 🔧

### Researcher Strategy (Plan-then-Execute)
The `researcher` flow generates a high-level research plan before executing tool calls. This improves reliability for multi-hop questions by separating planning and execution.

### Embeddings & Cache
Embeddings are cached per-tenant in `.cache/embeddings_<model>.pkl`. Delete the `.cache/` directory to force re-indexing after data changes.

### Search Analysis Debug Tab
In the web UI Chat view, the **Debug Logs** expander (open by default after a query) shows:
- **Reasoning Trace**: every LLM call/response in the turn
- **Search Analysis**: every tool call with its arguments, optional query-analyzer output, and raw results

---

## Developer Workflow

### Python tests

```bash
# From repo root
set -a && source .env && set +a
.venv/bin/python -m pytest python/tests/ -v
```

### Rust build & tests

```bash
cd rust
cargo build --release
cargo test
```

---

## Project Structure


```
EABench/
├── .env                         # Credentials (not committed)
├── python/                      # Web UI (Streamlit)
│   ├── requirements.txt
│   ├── app.py                   # Streamlit entry point
│   └── src/
│       ├── core/                # Agent runner, search engine, LLM/embedding providers
│       ├── config/              # Pydantic schemas (TenantConfig, AgentConfig)
│       ├── sandbox/             # LocalSandbox
│       └── eval/                # Evaluator, assertions, judge templates
│   └── tests/                   # Pytest suite (113 tests)
├── rust/                        # Offline CLI (data gen + eval)
│   ├── Cargo.toml
│   ├── example_cmd.md           # CLI usage reference
│   └── src/
│       ├── main.rs              # CLI: eval | generate | serve subcommands
│       ├── generator/           # Synthetic tenant generator (LLM-driven)
│       ├── eval/                # Deterministic evaluator
│       ├── search/              # Keyword search engine
│       └── config/              # TenantConfig, AgentConfig (Rust)
└── examples/
    ├── agents/                  # Agent YAML configs (react_agent.yaml, researcher_agent.yaml, …)
    ├── tenants/                 # Generated tenant datasets
    ├── evals/                   # Judge prompt configs
    └── generation/              # Prompt templates for data generation
```

---

## Troubleshooting & Tips

- If the UI fails to start, ensure no other server is on port 8501 and check `.env` for correct keys.
- Embeddings mismatch: delete tenant `.cache/` to force re-index.
- If a model produces invalid tool calls, enable the parser repair loop in the agent config to force the LLM to reformat outputs.

---

## Contributing & Governance

- Please open issues for bugs or feature requests.
- Open PRs against `main`. Follow the repo's code style and include tests for new features.

---

## License & Contact

This project is MIT-licensed — see `LICENSE`.
Questions or partnership inquiries: reach out via GitHub issues or email the maintainers listed in `AUTHORS.md`.
