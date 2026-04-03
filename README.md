# EABench - Agent Execution and Evaluation Platform

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/) [![Rust](https://img.shields.io/badge/rust-1.75%2B-orange.svg)](https://www.rust-lang.org/)

EABench is a modular platform to execute, test, and evaluate LLM-powered agents in hermetic sandboxes. It provides realistic synthetic tenant data (emails, chats, meetings, files), configurable agent workflows, secure tool execution, and an evaluation framework combining deterministic assertions with LLM-based judging.

**Architecture**: Rust handles offline data generation and evaluation; Python serves the interactive web UI.

---

## Highlights ✅

- **Rust CLI for data generation**: Fast, parallel tenant generation with `eabench generate`. Supports Azure OpenAI and OpenAI-compatible providers.
- **Streamlit Web UI**: Chat with agents, run evaluations, and inspect debug traces in the browser.
- **Sandboxed Execution**: Agents run in isolated local sandboxes with read/write/execute tool access.
- **Multi-Provider LLM Support**: Azure OpenAI, OpenAI-compatible endpoints (SiliconFlow, etc.), or local LLMs.
- **Embeddings & Caching**: Azure or local `sentence-transformers` embeddings, cached per-tenant as `.cache/*.pkl`.
- **Flexible Agent Strategies**: ReAct (interactive loop) and Researcher (Plan-then-Execute).
- **LLM-as-a-Judge Evaluation**: Deterministic assertions + configurable judge prompts for qualitative scoring.

---

## Quickstart 🚀

### 1. Prerequisites

```bash
git clone <repository-url>
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
cd rust
cargo build --release
# Binary at: rust/target/release/eabench
```

### 3. Set up Python (web UI only)

```bash
# From repo root
python3 -m venv .venv
.venv/bin/pip install -r python/requirements.txt
```

### 4. Generate a tenant with the Rust CLI

```bash
cd rust
set -a && source ../.env && set +a

# Small tenant (Azure)
cargo run --release -- generate \
  --company "Acme Corp" \
  --industry "Technology" \
  --description "A software startup building a SaaS product" \
  --events "Project Kickoff" "Q1 Review" \
  --size small \
  --num-users 5 \
  --days 7 \
  --provider azure

# Large tenant with many events (Azure)
cargo run --release -- generate \
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

Output is written to `../examples/tenants/<company-slug-YYYYMMDD>/`.

### 5. Launch the web UI

```bash
# Option A: via Rust CLI (run from rust/)
cargo run --release -- serve

# Option B: directly (run from repo root)
set -a && source .env && set +a
.venv/bin/streamlit run python/app.py --server.port 8501
```

Open **http://localhost:8501**, select a tenant and user from the sidebar, and start chatting.

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
- `tenant.yaml` — users, emails, chats, meetings, files metadata
- `data/` — actual file contents
- `docs/` — additional documents
- `.cache/` — precomputed embeddings cache (delete to force re-index)

---

## Rust CLI Reference

All commands are run from the `rust/` directory. Load credentials first:

```bash
set -a && source ../.env && set +a
```

### `generate` — Create a synthetic tenant

```bash
cargo run --release -- generate \
  --company    "Acme Corp" \
  --industry   "Technology" \
  --description "A software startup" \
  --events     "Project Kickoff" "Q1 Review" \
  --size       small \          # small | medium | large
  --num-users  5 \
  --days       7 \
  --provider   azure            # azure | openai
```

Optional flags:
- `--output <dir>` — output directory (default: `../examples/tenants`)
- `--prompts <path>` — prompt templates YAML (default: `../examples/generation/default_prompts.yaml`)
- `--model <name>` — override deployment/model name
- `--dry-run` — validate config without calling the LLM

### `eval` — Run deterministic evaluation

```bash
cargo run --release -- eval \
  --tenant  examples/tenants/test-tenant-1/tenant.yaml \
  --eval    examples/tenants/test-tenant-1/eval_set.yaml \
  --workers 4
```

### `serve` — Launch the web UI

```bash
cargo run --release -- serve              # default port 8501
cargo run --release -- serve --port 8502  # custom port
```

Looks for `.venv/bin/streamlit` in the repo root first, then falls back to `streamlit` on PATH.

---

## Eval Dataset Format

Generated eval datasets (`eval_dataset_<timestamp>.yaml`) follow this structure:

```yaml
name: "Acme Corp Evaluation"
description: "..."
cases:
  - id: case_001
    query: "Summarize the action items from the last deployment meeting."
    user_id: user123
    assertions:
      - contains: "action item"
    entity_list: []
```

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
