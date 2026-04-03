# EABench Rust CLI – Example Commands

## Setup: load credentials from .env

```bash
set -a && source ../.env && set +a
```

---

## Generate a synthetic tenant (OpenAI / SiliconFlow)

```bash
cargo run --release -- generate \
  --company "Acme Corp" \
  --industry "Technology" \
  --description "A software startup building a new SaaS product" \
  --events "Project Kickoff" "Q1 Review" \
  --size small \
  --num-users 5 \
  --days 7 \
  --provider openai
```

> Uses `OPENAI_API_KEY`, `OPENAI_API_BASE`, and `OPENAI_MODEL` from `.env`.

---

## Generate a synthetic tenant (Azure OpenAI)

```bash
cargo run --release -- generate \
  --company "Acme Corp" \
  --industry "Technology" \
  --description "A software startup building a new SaaS product" \
  --events "Project Kickoff" "Q1 Review" \
  --size small \
  --num-users 5 \
  --days 7 \
  --provider azure
```

> Uses `AZURE_API_KEY`, `AZURE_ENDPOINT`, and `AZURE_API_VERSION` from `.env`.

---

## Generate a large tenant with many events (Azure OpenAI)

```bash
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

---

## Dry-run (validate config without calling the LLM)

```bash
cargo run --release -- generate \
  --company "Acme Corp" \
  --industry "Technology" \
  --description "A software startup building a new SaaS product" \
  --dry-run
```

---

## Run evaluation

```bash
cargo run --release -- eval \
  --tenant ../examples/tenants/test-tenant-1/tenant.yaml \
  --eval   ../examples/tenants/test-tenant-1/eval_set.yaml \
  --workers 4
```

---

## Launch the web UI

```bash
cargo run --release -- serve
```

Custom port:

```bash
cargo run --release -- serve --port 8502
```

> Looks for `../.venv/bin/streamlit` first, then falls back to `streamlit` on PATH.
> App path defaults to `../python/app.py`. Run from the `rust/` directory.

