# EABench - Agent Execution and Evaluation Platform

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

EABench is a modular platform to execute, test, and evaluate LLM-powered agents in hermetic sandboxes. It provides realistic tenant data (emails, chats, meetings, files), configurable agent workflows, secure tool execution, and an evaluation framework that includes both deterministic assertions and LLM-based judging.

---

## Highlights ✅

- **Sandboxed Execution**: Run agents safely in isolated environments (Docker or local sandboxes).
- **Multi-Provider LLM Support**: Configure Azure OpenAI, OpenAI-compatible endpoints, or local LLMs via adapters.
- **Embeddings & Caching**: Support for local (`sentence-transformers`) or provider embeddings, plus local pickle-based caching to speed up startup.
- **Flexible Agent Strategies**: ReAct (interactive loop), Researcher (Plan-then-Execute), and configurable DAG flows.
- **Traceable & Testable**: OpenTelemetry-compatible traces and assertion-driven tests + LLM-as-a-Judge evaluations.
- **Extensible Tooling**: Register new tools with `@tool` decorators and restrict capabilities per-agent via config.

---

## Quickstart 🚀

1. Clone and setup:

```bash
git clone <repository-url>
cd EABench
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure credentials (see **Configuration** below). Add a `.env` file in the repo root; do NOT commit secrets.

3. Start the web UI (recommended):

```bash
python -m streamlit run app.py
```

4. Open `http://localhost:8501`, pick a tenant user, and ask the agent questions.

---

## Configuration

- Environment variables are defined in `.env`:
  - For Azure: `AZURE_API_KEY`, `AZURE_ENDPOINT`, `AZURE_API_VERSION`.
  - For OpenAI: `OPENAI_API_KEY`, `OPENAI_API_BASE`.

- Agent configs live in `examples/agents/`. You can change model, embedding provider, prompts, and flow strategy in YAML.

- Tenants & test data live under `examples/tenants/` (create new tenants by copying an existing folder and editing its YAML). Each tenant contains:
  - user definitions
  - files (documents, emails)
  - tenant-level settings (resource limits, protected files)

- **Tenant generation (recommended)**: For large-scale or reproducible evaluation, generate tenants programmatically. The generator accepts options like `--users`, `--seed`, and `--scenario` and outputs a tenant folder with `tenant.yaml`, a `files/` directory, and an optional `.cache/` for cached embeddings.

  Use the real CLI tools provided in the repo:

  - To generate a new tenant, use `generate_data.py` which accepts `--company`, `--industry`, `--size`, `--num_users`, `--days`, `--events`, `--description`, and `--prompts`.

  Example:
  ```bash
  python generate_data.py \
    --company "Acme Corp" \
    --industry "SaaS" \
    --size small \
    --num_users 20 \
    --days 14 \
    --eval_batch_size 10 \
    --events "Project Alpha Kickoff" "Memory Leak Incident" \
    --description "Incident response training scenario" \
    --prompts examples/generation/default_prompts.yaml
  ```

  Output layout (example):
  - `examples/tenants/<tenant-id>/tenant.yaml`
  - `examples/tenants/<tenant-id>/files/` (documents, emails, meeting notes)
  - `examples/tenants/<tenant-id>/.cache/` (optional precomputed embeddings)

- **Evaluation query sets**: Place a canonical `eval_queries.yaml` in the tenant folder to define reproducible test queries. Each entry should include `id`, `prompt`, `expected_assertions` (for deterministic checks), `difficulty`, `tags`, and optional `ground_truth_refs` used by Judges.

  Example query entry:
  ```yaml
  - id: q1
    prompt: "Summarize the action items from the last deployment meeting."
    expected_assertions:
      - file_contains: {path: "files/meeting_notes/notes_2025-11-10.txt", contains: "action item"}
    difficulty: easy
    tags: [meeting, summary]
  ```

  Best practices:
  - Use deterministic seeds for reproducible tenant and query generation.
  - Create paraphrase variants to test robustness.
  - Tag queries with difficulty and rubric hints for Judge models.
  - Keep query sets version-controlled alongside tenants.

**Security note**: Never check secrets into git. Use a secrets manager or `.env` with `.gitignore`.

---

## Important Concepts & Features 🔧

### Researcher Strategy (Plan-then-Execute)
The `researcher` flow generates a high-level plan before executing steps. This improves reliability for multi-hop or long-horizon tasks by separating planning and execution and sanitizing the final output to hide internal planning artifacts.

### Embeddings & Local Cache
Embeddings are cached per-tenant in a `.cache/` directory inside the tenant root. The cache keys are based on file content hashes to support invalidation when files change. This dramatically reduces startup indexing latency for large datasets.

### Observability & Evaluation
- Traces follow OpenTelemetry conventions to capture reasoning spans, tool calls, and observations.
- Evaluation combines deterministic assertions (file state, tool usage) with an LLM-based Judge for qualitative measures like faithfulness and reasoning quality.

---

## Usage Patterns

### Web UI (Interactive)

```bash
python -m streamlit run app.py
```

- Switch users from the sidebar to change agent permissions and data visibility.
- Try queries such as: "Summarize action items from the last meeting." or "Find emails referencing the memory leak."

### CLI (Batch/Eval)

- `python main.py` runs the CLI demo (indexes a tenant and executes a sample query).
- Use evaluation scripts in `src/eval/` to run test suites and collect Judge scores.

---

## Developer Workflow

- Run tests:
  ```bash
  pytest -q
  ```

- Lint & format:
  ```bash
  black . && ruff .
  ```

- Run a single agent locally (example):
  ```bash
  python -m src.core.agent_runner --agent examples/agents/researcher_agent.yaml --tenant examples/tenants/test-tenant-1
  ```

- Add a new tool: create a function and decorate with `@tool`, include an args schema (Pydantic) and register it in the ToolRegistry.

---

## Project Structure

- `src/core/`: Agent runtime, provider adapters, runner, and search engine (includes caching logic).
- `src/config/`: Pydantic schemas for agent, tenant, and flow configs.
- `src/sandbox/`: Sandbox implementations (DockerSandbox, LocalSandbox).
- `src/eval/`: Evaluation runner, assertions, Judge prompt templates.
- `examples/agents/`: Agent YAMLs (react_agent.yaml, researcher_agent.yaml).
- `examples/tenants/`: Tenant test datasets.
- `app.py`: Streamlit UI.
- `main.py`: CLI entrypoint.

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
