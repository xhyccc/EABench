# EABench – Rust Implementation

A Rust port of the core EABench system, providing the same concepts as the
Python implementation:

- **Config** – Tenant and Agent configuration loaded from YAML files.
- **Sandbox** – Isolated `LocalSandbox` for safe file I/O and command
  execution inside a temporary directory.
- **Search** – Keyword-based `SearchEngine` over tenant data (files, emails,
  chats, meetings, users).
- **Eval** – Deterministic assertion-based `Evaluator` with aggregate
  statistics.

## Requirements

- Rust 1.70+ (edition 2021)
- Cargo

## Quickstart

```bash
# Build
cargo build

# Run the CLI entry point
cargo run

# Run all tests
cargo test
```

## Project Structure

```
rust/
├── Cargo.toml
├── README.md
└── src/
    ├── lib.rs          # Library root (re-exports modules)
    ├── main.rs         # CLI entry point
    ├── config/
    │   ├── mod.rs
    │   ├── tenant_config.rs   # TenantConfig + sub-models
    │   └── agent_config.rs    # AgentConfig + sub-models
    ├── sandbox/
    │   ├── mod.rs             # Sandbox trait
    │   └── local_sandbox.rs   # LocalSandbox implementation
    ├── search/
    │   ├── mod.rs
    │   └── search_engine.rs   # Keyword SearchEngine
    └── eval/
        ├── mod.rs
        ├── models.rs          # Assertion, EvaluationCase, EvaluationResult
        └── evaluator.rs       # Deterministic Evaluator
```

## Running Tests

```bash
cargo test
```

All unit tests live next to the code they test in `#[cfg(test)]` modules.
72 tests cover:

- Config YAML loading and field defaults
- Sandbox lifecycle (start/stop/hydrate), file operations, path-traversal
  security
- Search engine keyword scoring and all search methods
- Evaluation assertion checking, batch evaluation, aggregate statistics

## Design Notes

- **No async**: The Rust version uses synchronous I/O (no `tokio`), keeping
  the code straightforward and dependency-light.
- **No embeddings**: The `SearchEngine` uses simple keyword-overlap scoring
  instead of vector embeddings, so it works offline with no API keys.
- **Deterministic evaluation**: The `Evaluator` checks assertions via
  keyword matching rather than an LLM judge, making tests fully reproducible.
