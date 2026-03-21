# EABench – Rust Implementation

A standalone Rust port of the core EABench system.  It runs **independently**
of the Python version – no Python interpreter, virtualenv, or Python
dependencies are required.

Capabilities:

- **Config** – Tenant and Agent configuration loaded from YAML files.
- **Sandbox** – Isolated `LocalSandbox` for safe file I/O and command
  execution inside a temporary directory.
- **Search** – Keyword-based `SearchEngine` over tenant data (files, emails,
  chats, meetings, users), including a `search_all` method that fans out
  across all data types.
- **Eval** – Deterministic assertion-based `Evaluator` with both sequential
  (`evaluate_batch`) and **parallel** (`evaluate_batch_parallel`) runners.

## Requirements

- Rust 1.70+ (edition 2021)
- Cargo
- No Python, no external services, no API keys needed for evaluation

## Quickstart

```bash
cd rust

# Build
cargo build

# Run the CLI with default paths (requires examples/ in the repo root)
cargo run

# Run tests
cargo test
```

## CLI Reference

```
cargo run -- [OPTIONS]

OPTIONS:
  --tenant PATH    Path to tenant.yaml
                   (default: examples/tenants/test-tenant-1/tenant.yaml)
  --eval   PATH    Path to evaluation set YAML
                   (default: examples/tenants/test-tenant-1/eval_set.yaml)
  --workers N      Number of parallel worker threads (default: 0 = auto)
  --help           Print usage
```

### Examples

```bash
# 4 parallel workers
cargo run -- \
    --tenant examples/tenants/test-tenant-1/tenant.yaml \
    --eval   examples/tenants/test-tenant-1/eval_set.yaml \
    --workers 4

# Let rayon choose the thread count automatically (= logical CPU count)
cargo run -- --workers 0

# Single-threaded (useful for debugging)
cargo run -- --workers 1
```

## Parallel Evaluation

The `Evaluator::evaluate_batch_parallel` method runs each evaluation case on
its own worker thread using [Rayon](https://github.com/rayon-rs/rayon):

```rust
use eabench_lib::eval::{Evaluator, EvaluationSet};

let evaluator = Evaluator::new();

// scorer: Fn(&str) -> (String, Vec<String>) + Send + Sync
let results = evaluator.evaluate_batch_parallel(
    &eval_set,
    |query| {
        // each worker independently handles one query
        let response = my_agent.run(query);
        (response, vec!["tool_a".to_string()])
    },
    4,   // num_workers; 0 = auto (logical CPU count)
);
```

Key properties:
- Results are returned **in the same order** as `eval_set.cases`.
- `num_workers = 0` tells Rayon to pick the thread count automatically
  (equals the number of logical CPUs on the host).
- The scorer closure must be `Fn + Send + Sync` so it can be called from
  multiple threads simultaneously.

## Project Structure

```
rust/
├── Cargo.toml
├── README.md
└── src/
    ├── lib.rs          # Library root (re-exports modules)
    ├── main.rs         # Standalone CLI entry point
    ├── config/
    │   ├── mod.rs
    │   ├── tenant_config.rs   # TenantConfig + sub-models
    │   └── agent_config.rs    # AgentConfig + sub-models
    ├── sandbox/
    │   ├── mod.rs             # Sandbox trait
    │   └── local_sandbox.rs   # LocalSandbox implementation
    ├── search/
    │   ├── mod.rs
    │   └── search_engine.rs   # Keyword SearchEngine (incl. search_all)
    └── eval/
        ├── mod.rs
        ├── models.rs          # Assertion, EvaluationCase, EvaluationResult
        └── evaluator.rs       # Evaluator (sequential + parallel batch)
```

## Running Tests

```bash
cargo test
```

All unit tests live next to the code they test in `#[cfg(test)]` modules.
82 tests cover:

- Config YAML loading and field defaults
- Sandbox lifecycle (start/stop/hydrate), file operations, path-traversal
  security
- Search engine keyword scoring, all search methods, and `search_all`
- Evaluation assertion checking, sequential batch, **parallel batch**
  (order preservation, single/multi/auto workers, empty set, sequential
  parity), and aggregate statistics

- Config YAML loading and field defaults
- Sandbox lifecycle (start/stop/hydrate), file operations, path-traversal
  security
- Search engine keyword scoring, all search methods, and `search_all`
- Evaluation assertion checking, sequential batch, **parallel batch**
  (order preservation, single/multi/auto workers, empty set, sequential
  parity), and aggregate statistics

## Design Notes

- **Standalone**: No Python runtime or external services required.  The CLI
  can be built with a single `cargo build` and run directly.
- **Parallel evaluation**: Uses [Rayon](https://github.com/rayon-rs/rayon)
  work-stealing thread pool.  Worker count is fully configurable via
  `--workers` (CLI) or the `num_workers` argument to
  `evaluate_batch_parallel`.  Pass `0` to auto-size to logical CPU count.
- **No async**: Synchronous I/O keeps the code straightforward.  The
  parallelism is CPU-level (Rayon) rather than I/O-level (Tokio).
- **No embeddings**: The `SearchEngine` uses simple keyword-overlap scoring,
  working offline with no API keys.
- **Deterministic evaluation**: Assertions are checked via keyword matching,
  making test runs fully reproducible.
