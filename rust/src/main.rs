/// EABench CLI entry point.
///
/// # Usage
///
/// ```text
/// # Run with defaults (looks for examples/ relative to the binary)
/// cargo run
///
/// # Parallel evaluation against an eval set
/// cargo run -- \
///     --tenant examples/tenants/test-tenant-1/tenant.yaml \
///     --eval   examples/tenants/test-tenant-1/eval_set.yaml \
///     --workers 4
/// ```
///
/// Options
/// -------
/// --tenant  PATH   Path to tenant.yaml  (default: examples/tenants/test-tenant-1/tenant.yaml)
/// --eval    PATH   Path to eval YAML    (default: examples/tenants/test-tenant-1/eval_set.yaml)
/// --workers N      Parallel worker count (default: 0 = auto / logical CPU count)

use std::path::PathBuf;
use anyhow::{Context, Result};

use eabench_lib::config::TenantConfig;
use eabench_lib::eval::{Evaluator, EvaluationSet};
use eabench_lib::search::SearchEngine;

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();

    // -----------------------------------------------------------------------
    // Parse CLI arguments
    // -----------------------------------------------------------------------
    let (tenant_path, eval_path, num_workers) = parse_args(&args)?;

    println!("EABench – Agent Execution and Evaluation Platform (Rust)");
    println!("----------------------------------------------------------");
    println!("Tenant config : {}", tenant_path.display());
    println!("Eval set      : {}", eval_path.display());
    println!(
        "Workers       : {}",
        if num_workers == 0 {
            "auto (logical CPU count)".to_string()
        } else {
            num_workers.to_string()
        }
    );
    println!();

    // -----------------------------------------------------------------------
    // Load configs
    // -----------------------------------------------------------------------
    let tenant = TenantConfig::from_yaml(&tenant_path)
        .with_context(|| format!("loading tenant config from {}", tenant_path.display()))?;

    println!(
        "Loaded tenant '{}' ({} users, {} files)",
        tenant.id,
        tenant.users.len(),
        tenant.files_metadata.len()
    );

    let raw_eval = std::fs::read_to_string(&eval_path)
        .with_context(|| format!("reading eval set from {}", eval_path.display()))?;
    let eval_set: EvaluationSet = serde_yaml::from_str(&raw_eval)
        .with_context(|| format!("parsing eval set from {}", eval_path.display()))?;

    println!(
        "Loaded eval set '{}' ({} cases)",
        eval_set.name,
        eval_set.cases.len()
    );
    println!();

    // -----------------------------------------------------------------------
    // Build search engine (used inside the scorer)
    // -----------------------------------------------------------------------
    let search_engine = SearchEngine::new(tenant.clone());

    // -----------------------------------------------------------------------
    // Run parallel evaluation
    // -----------------------------------------------------------------------
    println!(
        "Running evaluation with {} worker(s)…",
        if num_workers == 0 { "auto".to_string() } else { num_workers.to_string() }
    );

    let evaluator = Evaluator::new();

    // The scorer uses the keyword-based search engine to generate a simple
    // response for each query.  In production you would replace this with a
    // real LLM call; the parallel infrastructure handles the concurrency.
    let results = evaluator.evaluate_batch_parallel(
        &eval_set,
        |query| {
            let hits = search_engine.search_all(query, 3);
            let response = if hits.is_empty() {
                format!("No relevant information found for: {}", query)
            } else {
                hits.iter()
                    .map(|h| format!("[{}] {}: {}", h.kind, h.title, h.snippet))
                    .collect::<Vec<_>>()
                    .join("\n")
            };
            (response, vec![])
        },
        num_workers,
    );

    // -----------------------------------------------------------------------
    // Print per-case results
    // -----------------------------------------------------------------------
    println!("\nResults:");
    println!("{:-<60}", "");
    for result in &results {
        // Add 0.0 to normalize IEEE 754 negative-zero to positive-zero for display.
        println!(
            "[{}] {} | assertion={:.2} | tool={:.2} | overall={:.2} | {}",
            if result.passed { "PASS" } else { "FAIL" },
            result.case_id,
            result.metrics.get("assertion_score").copied().unwrap_or(0.0) + 0.0,
            result.metrics.get("tool_score").copied().unwrap_or(0.0) + 0.0,
            result.metrics.get("overall_score").copied().unwrap_or(0.0) + 0.0,
            result.reasoning,
        );
    }

    // -----------------------------------------------------------------------
    // Print aggregate summary
    // -----------------------------------------------------------------------
    println!("{:-<60}", "");
    let pass_rate = Evaluator::aggregate_pass_rate(&results);
    let mean_score = Evaluator::mean_assertion_score(&results) + 0.0;
    println!(
        "Pass rate       : {}/{} ({:.1}%)",
        results.iter().filter(|r| r.passed).count(),
        results.len(),
        pass_rate * 100.0,
    );
    println!("Mean assertion  : {:.3}", mean_score);
    println!("{:-<60}", "");

    Ok(())
}

// ---------------------------------------------------------------------------
// Argument parsing
// ---------------------------------------------------------------------------

fn parse_args(args: &[String]) -> Result<(PathBuf, PathBuf, usize)> {
    let mut tenant_path = PathBuf::from("examples/tenants/test-tenant-1/tenant.yaml");
    let mut eval_path   = PathBuf::from("examples/tenants/test-tenant-1/eval_set.yaml");
    let mut num_workers: usize = 0;

    let mut i = 1usize;
    while i < args.len() {
        match args[i].as_str() {
            "--tenant" => {
                i += 1;
                tenant_path = PathBuf::from(
                    args.get(i).context("--tenant requires a PATH argument")?,
                );
            }
            "--eval" => {
                i += 1;
                eval_path = PathBuf::from(
                    args.get(i).context("--eval requires a PATH argument")?,
                );
            }
            "--workers" => {
                i += 1;
                let n = args.get(i).context("--workers requires a NUMBER argument")?;
                num_workers = n.parse::<usize>()
                    .with_context(|| format!("--workers value '{}' is not a valid number", n))?;
            }
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            other => {
                anyhow::bail!("Unknown argument '{}'. Use --help for usage.", other);
            }
        }
        i += 1;
    }

    Ok((tenant_path, eval_path, num_workers))
}

fn print_usage() {
    println!(
        "EABench – Rust evaluation runner\n\
         \n\
         USAGE:\n\
         \x20   cargo run -- [OPTIONS]\n\
         \n\
         OPTIONS:\n\
         \x20   --tenant PATH    Path to tenant.yaml  (default: examples/tenants/test-tenant-1/tenant.yaml)\n\
         \x20   --eval   PATH    Path to eval YAML    (default: examples/tenants/test-tenant-1/eval_set.yaml)\n\
         \x20   --workers N      Parallel worker threads (default: 0 = auto)\n\
         \x20   --help           Print this message\n"
    );
}
