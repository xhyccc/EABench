# EABench Rust CLI – Example Commands

## Setup: load credentials from .env

```bash
set -a && source ../.env && set +a
```

---

## Generate a synthetic tenant (OpenAI / SiliconFlow)

```bash
cargo run -- generate \
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
cargo run -- generate \
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

## Dry-run (validate config without calling the LLM)

```bash
cargo run -- generate \
  --company "Acme Corp" \
  --industry "Technology" \
  --description "A software startup building a new SaaS product" \
  --dry-run
```

---

## Run evaluation

```bash
cargo run -- eval \
  --tenant examples/tenants/test-tenant-1/tenant.yaml \
  --eval   examples/tenants/test-tenant-1/eval_set.yaml \
  --workers 4
```
