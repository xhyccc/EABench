/// EABench CLI entry point.
///
/// # Usage
///
/// ```text
/// # Evaluate (default mode)
/// cargo run -- eval \
///     --tenant examples/tenants/test-tenant-1/tenant.yaml \
///     --eval   examples/tenants/test-tenant-1/eval_set.yaml \
///     --workers 4
///
/// # Generate a new synthetic tenant
/// cargo run -- generate \
///     --company "Acme Corp" \
///     --industry "Technology" \
///     --description "A software startup building a new SaaS product" \
///     --events "Project Kickoff" "Q1 Review" \
///     --size small \
///     --num-users 5 \
///     --days 7 \
///     --output examples/tenants \
///     --prompts examples/generation/default_prompts.yaml
/// ```

use std::path::PathBuf;
use anyhow::{Context, Result};
use rayon::prelude::*;

use eabench_lib::config::TenantConfig;
use eabench_lib::eval::{EvaluationSet, run_react_agent, judge_assertions, judge_citation};
use eabench_lib::search::SearchEngine;
use eabench_lib::generator::{DataGenerator, StoryConfig, OpenAIProvider, AzureOpenAIProvider, LLMProvider};
use std::sync::Arc;

// ---------------------------------------------------------------------------
// Judge-config structs (parsed from the judge YAML, e.g. default_judge.yaml)
// ---------------------------------------------------------------------------

#[derive(Debug, serde::Deserialize)]
struct JudgePromptConfig {
    assertion_check: String,
    citation_relevance: String,
    #[serde(default)]
    side_by_side: String,
}

#[derive(Debug, serde::Deserialize)]
struct JudgeConfig {
    #[allow(dead_code)]
    name: String,
    #[serde(default)]
    #[allow(dead_code)]
    description: String,
    prompts: JudgePromptConfig,
}

// ---------------------------------------------------------------------------
// Subcommand enum
// ---------------------------------------------------------------------------

enum Command {
    Eval(EvalArgs),
    Generate(GenerateArgs),
    Serve(ServeArgs),
}

struct ServeArgs {
    /// Port for the Streamlit server (default 8501)
    port: u16,
    /// Path to the app.py to launch (default: ../python/app.py)
    app: String,
}

struct EvalArgs {
    tenant_path: PathBuf,
    eval_path: PathBuf,
    num_workers: usize,

    // LLM provider (inherits same env-var / flag logic as generate)
    provider: Option<String>,
    model: Option<String>,
    api_key: Option<String>,
    base_url: Option<String>,
    azure_endpoint: Option<String>,
    azure_deployment: Option<String>,
    api_version: Option<String>,
    temperature: f64,

    // Agent / judge
    agent_config_path: Option<PathBuf>,
    judge_config_path: PathBuf,
    max_turns: usize,
}

struct GenerateArgs {
    // Story config (can be loaded from file and/or overridden by flags)
    config_file: Option<String>,
    company: Option<String>,
    industry: Option<String>,
    description: Option<String>,
    events: Vec<String>,
    size: Option<String>,
    num_users: Option<usize>,
    days: Option<usize>,
    eval_batch_size: Option<usize>,

    // Output / prompts
    output_dir: String,
    prompts_path: String,

    // LLM provider selection
    provider: Option<String>,    // "openai" | "azure"  (auto-detect if omitted)
    model: Option<String>,
    api_key: Option<String>,
    base_url: Option<String>,    // OpenAI: custom base URL
    azure_endpoint: Option<String>,
    azure_deployment: Option<String>,
    api_version: Option<String>,
    temperature: f64,

    // Behaviour flags
    dry_run: bool,
}

// ---------------------------------------------------------------------------
// Path resolution helper
// ---------------------------------------------------------------------------

/// Resolves a path that may be relative to the **repo root** or to `rust/`,
/// regardless of the current working directory.
///
/// Tries, in order:
///   1. Path as-is (already correct).
///   2. Strip a leading `"../"` component — converts a `rust/`-relative default
///      like `"../examples/tenants"` into `"examples/tenants"` for callers
///      sitting at the repo root.
///   3. Prepend `"../"` — converts a repo-root-relative path like
///      `"examples/tenants/…"` into `"../examples/tenants/…"` for callers
///      sitting inside `rust/`.
///   4. Return the original path so the caller receives a meaningful error.
fn resolve_path(p: PathBuf) -> PathBuf {
    if p.exists() {
        return p;
    }
    // Case: running from repo root with a "../"-prefixed default (designed for rust/ CWD)
    if let Ok(stripped) = p.strip_prefix("..") {
        if stripped.exists() {
            return stripped.to_path_buf();
        }
    }
    // Case: running from rust/ with a path relative to repo root
    let with_parent = PathBuf::from("..").join(&p);
    if with_parent.exists() {
        return with_parent;
    }
    p // return original so the caller gets a meaningful error
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();

    match parse_args(&args)? {
        Command::Eval(a)     => run_eval(a),
        Command::Generate(a) => run_generate(a),
        Command::Serve(a)    => run_serve(a),
    }
}

// ---------------------------------------------------------------------------
// serve subcommand
// ---------------------------------------------------------------------------

fn run_serve(a: ServeArgs) -> Result<()> {
    let app_path = std::fs::canonicalize(&a.app)
        .with_context(|| format!("app not found at '{}' — is the path correct? (run from the repo root or rust/)", a.app))?;

    println!("EABench – Web UI");
    println!("----------------");
    println!("App    : {}", app_path.display());
    println!("Port   : {}", a.port);
    println!("URL    : http://localhost:{}", a.port);
    println!();

    let streamlit = which_streamlit()?;
    println!("Launching: {} run {} --server.port {}", streamlit, app_path.display(), a.port);
    println!("Press Ctrl+C to stop.");
    println!();

    let status = std::process::Command::new(&streamlit)
        .args(["run", app_path.to_str().unwrap(), "--server.port", &a.port.to_string()])
        .status()
        .with_context(|| format!("failed to launch streamlit ('{}' not found — is the Python venv activated?)", streamlit))?;

    if !status.success() {
        anyhow::bail!("streamlit exited with status: {}", status);
    }
    Ok(())
}

/// Find the `streamlit` executable: repo root .venv first, then rust/ parent .venv, then PATH.
fn which_streamlit() -> Result<String> {
    for candidate in &[".venv/bin/streamlit", "../.venv/bin/streamlit"] {
        if std::path::Path::new(candidate).exists() {
            return Ok(candidate.to_string());
        }
    }
    Ok("streamlit".to_string())
}

// ---------------------------------------------------------------------------
// eval subcommand
// ---------------------------------------------------------------------------

// Default system prompt used when no agent config is provided.
const DEFAULT_SYSTEM_PROMPT: &str =
    "You are an intelligent enterprise assistant. \
     Use the available search tools to find relevant information from the user's \
     emails, files, chats, and meetings before answering. \
     Always base your answers on retrieved data, not assumptions.";

fn run_eval(a: EvalArgs) -> Result<()> {
    println!("EABench – Agent Execution and Evaluation Platform (Rust)");
    println!("----------------------------------------------------------");
    println!("Tenant config : {}", a.tenant_path.display());
    println!("Eval set      : {}", a.eval_path.display());
    println!("Judge config  : {}", a.judge_config_path.display());
    println!("Max turns     : {}", a.max_turns);
    println!(
        "Workers       : {}",
        if a.num_workers == 0 { "auto (logical CPU count)".to_string() } else { a.num_workers.to_string() }
    );
    println!();

    // -----------------------------------------------------------------------
    // Load tenant and eval set
    // -----------------------------------------------------------------------
    let tenant = TenantConfig::from_yaml(&a.tenant_path)
        .with_context(|| format!("loading tenant config from {}", a.tenant_path.display()))?;

    println!(
        "Loaded tenant '{}' ({} users, {} files)",
        tenant.id,
        tenant.users.len(),
        tenant.files_metadata.len()
    );

    let raw_eval = std::fs::read_to_string(&a.eval_path)
        .with_context(|| format!("reading eval set from {}", a.eval_path.display()))?;
    let eval_set: EvaluationSet = serde_yaml::from_str(&raw_eval)
        .with_context(|| format!("parsing eval set from {}", a.eval_path.display()))?;

    println!(
        "Loaded eval set '{}' ({} cases)",
        eval_set.name,
        eval_set.cases.len()
    );

    // -----------------------------------------------------------------------
    // Build LLM provider (same resolution logic as generate)
    // -----------------------------------------------------------------------
    let effective_provider = a.provider
        .clone()
        .unwrap_or_else(|| {
            if a.azure_endpoint.is_some() || std::env::var("AZURE_OPENAI_API_KEY").is_ok() {
                "azure".to_string()
            } else {
                "openai".to_string()
            }
        });

    let llm: Arc<dyn LLMProvider> = match effective_provider.as_str() {
        "azure" => {
            let key = a.api_key.clone()
                .or_else(|| std::env::var("AZURE_OPENAI_API_KEY").ok())
                .or_else(|| std::env::var("AZURE_API_KEY").ok())
                .context("Azure provider: supply --api-key or set AZURE_OPENAI_API_KEY")?;
            let endpoint = a.azure_endpoint.clone()
                .or_else(|| std::env::var("AZURE_OPENAI_ENDPOINT").ok())
                .or_else(|| std::env::var("AZURE_ENDPOINT").ok())
                .context("Azure provider: supply --azure-endpoint or set AZURE_OPENAI_ENDPOINT")?;
            let deployment = a.azure_deployment.clone()
                .or_else(|| a.model.clone())
                .or_else(|| std::env::var("AZURE_OPENAI_DEPLOYMENT_NAME").ok())
                .or_else(|| std::env::var("AZURE_DEPLOYMENT_NAME").ok())
                .unwrap_or_else(|| "gpt-4o".to_string());
            let api_version = a.api_version.clone()
                .or_else(|| std::env::var("AZURE_OPENAI_API_VERSION").ok())
                .or_else(|| std::env::var("AZURE_API_VERSION").ok())
                .unwrap_or_else(|| "2024-02-15-preview".to_string());
            println!("LLM provider   : Azure OpenAI");
            println!("  Endpoint     : {}", endpoint);
            println!("  Deployment   : {}", deployment);
            println!("  API version  : {}", api_version);
            Arc::new(AzureOpenAIProvider::new(key, endpoint, deployment, api_version, a.temperature))
        }
        _ => {
            let key = a.api_key.clone()
                .or_else(|| std::env::var("OPENAI_API_KEY").ok())
                .context("OpenAI provider: supply --api-key or set OPENAI_API_KEY")?;
            let base_url = a.base_url.clone()
                .or_else(|| std::env::var("OPENAI_BASE_URL").ok())
                .or_else(|| std::env::var("OPENAI_API_BASE").ok());
            let model = a.model.clone()
                .or_else(|| std::env::var("OPENAI_MODEL").ok())
                .unwrap_or_else(|| "gpt-4o".to_string());
            println!("LLM provider   : OpenAI");
            println!("  Model        : {}", model);
            if let Some(ref url) = base_url {
                println!("  Base URL     : {}", url);
            }
            Arc::new(OpenAIProvider::new(key, base_url, model, a.temperature))
        }
    };

    // -----------------------------------------------------------------------
    // Load judge config
    // -----------------------------------------------------------------------
    let raw_judge = std::fs::read_to_string(&a.judge_config_path)
        .with_context(|| format!("reading judge config from {}", a.judge_config_path.display()))?;
    let judge_cfg: JudgeConfig = serde_yaml::from_str(&raw_judge)
        .with_context(|| format!("parsing judge config from {}", a.judge_config_path.display()))?;

    // -----------------------------------------------------------------------
    // Load system prompt
    // -----------------------------------------------------------------------
    let system_prompt: String = if let Some(ref agent_path) = a.agent_config_path {
        let raw = std::fs::read_to_string(agent_path)
            .with_context(|| format!("reading agent config from {}", agent_path.display()))?;
        let v: serde_yaml::Value = serde_yaml::from_str(&raw)
            .with_context(|| format!("parsing agent config from {}", agent_path.display()))?;
        v.get("system_prompt")
            .and_then(|v| v.as_str())
            .unwrap_or(DEFAULT_SYSTEM_PROMPT)
            .to_string()
    } else {
        DEFAULT_SYSTEM_PROMPT.to_string()
    };

    println!();
    println!(
        "Running LLM evaluation with {} worker(s)…",
        if a.num_workers == 0 { "auto".to_string() } else { a.num_workers.to_string() }
    );
    println!();

    // -----------------------------------------------------------------------
    // Set Rayon thread pool size
    // -----------------------------------------------------------------------
    if a.num_workers > 0 {
        rayon::ThreadPoolBuilder::new()
            .num_threads(a.num_workers)
            .build_global()
            .ok(); // ignore error if already initialised
    }

    // -----------------------------------------------------------------------
    // Parallel evaluation: one full LLM pipeline per case
    // -----------------------------------------------------------------------
    let assertion_check_prompt = judge_cfg.prompts.assertion_check.clone();
    let citation_prompt        = judge_cfg.prompts.citation_relevance.clone();
    let max_turns              = a.max_turns;

    let results: Vec<eabench_lib::eval::EvaluationResult> = eval_set.cases
        .par_iter()
        .map(|case| {
            let llm_ref   = Arc::clone(&llm);
            let mut se    = SearchEngine::new(tenant.clone());
            let user_id   = case.user_id.as_deref();

            // 1. Run the ReAct agent to get a response + tool-call log.
            let (response, tool_calls_log) = match run_react_agent(
                llm_ref.as_ref(),
                &mut se,
                &system_prompt,
                user_id,
                &case.query,
                max_turns,
            ) {
                Ok(res) => (res.response, res.tool_calls_log),
                Err(e) => {
                    let msg = format!("[agent error] {}", e);
                    (msg, vec![])
                }
            };

            // 2. LLM judge: assertions
            let (assertion_score, assertion_results) =
                judge_assertions(
                    llm_ref.as_ref(),
                    &assertion_check_prompt,
                    &case.query,
                    &response,
                    &case.assertions,
                )
                .unwrap_or_else(|_| (0.0, vec![]));

            // 3. LLM judge: citation / tool-call quality
            let citation_score =
                judge_citation(
                    llm_ref.as_ref(),
                    &citation_prompt,
                    &case.query,
                    &tool_calls_log,
                    &response,
                )
                .unwrap_or(0.0);

            // 4. Pass/fail threshold (mirrors Python: assertion >= 0.75 AND citation >= 0.7)
            let passed = assertion_score >= 0.75 && citation_score >= 0.7;

            let tool_call_names: Vec<String> = tool_calls_log
                .iter()
                .map(|(name, _)| name.clone())
                .collect();

            let mut metrics = std::collections::HashMap::new();
            metrics.insert("assertion_score".to_string(), assertion_score);
            metrics.insert("citation_score".to_string(), citation_score);
            metrics.insert("overall_score".to_string(), (assertion_score + citation_score) / 2.0);

            let reasoning = format!(
                "assertion={:.2}, citation={:.2}",
                assertion_score, citation_score
            );

            eabench_lib::eval::EvaluationResult {
                case_id: case.id.clone(),
                query: case.query.clone(),
                response,
                tool_calls: tool_call_names,
                metrics,
                assertion_results,
                reasoning,
                passed,
            }
        })
        .collect();

    // -----------------------------------------------------------------------
    // Print results
    // -----------------------------------------------------------------------
    println!("Results:");
    println!("{:-<70}", "");
    for result in &results {
        println!(
            "[{}] {} | assertion={:.2} | citation={:.2} | overall={:.2}",
            if result.passed { "PASS" } else { "FAIL" },
            result.case_id,
            result.metrics.get("assertion_score").copied().unwrap_or(0.0),
            result.metrics.get("citation_score").copied().unwrap_or(0.0),
            result.metrics.get("overall_score").copied().unwrap_or(0.0),
        );
    }

    println!("{:-<70}", "");
    let total = results.len();
    let passed = results.iter().filter(|r| r.passed).count();
    let mean_assertion = if total > 0 {
        results.iter().map(|r| r.metrics.get("assertion_score").copied().unwrap_or(0.0)).sum::<f64>() / total as f64
    } else { 0.0 };
    let mean_citation = if total > 0 {
        results.iter().map(|r| r.metrics.get("citation_score").copied().unwrap_or(0.0)).sum::<f64>() / total as f64
    } else { 0.0 };

    println!(
        "Pass rate       : {}/{} ({:.1}%)",
        passed, total,
        if total > 0 { passed as f64 / total as f64 * 100.0 } else { 0.0 },
    );
    println!("Mean assertion  : {:.3}", mean_assertion);
    println!("Mean citation   : {:.3}", mean_citation);
    println!("{:-<70}", "");

    Ok(())
}

// ---------------------------------------------------------------------------
// generate subcommand
// ---------------------------------------------------------------------------

fn run_generate(a: GenerateArgs) -> Result<()> {
    // -----------------------------------------------------------------------
    // Resolve StoryConfig: start from YAML file (if given), then apply flags
    // -----------------------------------------------------------------------
    let mut story: StoryConfig = if let Some(ref path) = a.config_file {
        let raw = std::fs::read_to_string(path)
            .with_context(|| format!("reading story config from {}", path))?;
        serde_yaml::from_str(&raw)
            .with_context(|| format!("parsing story config from {}", path))?
    } else {
        // Require the three mandatory fields when no config file is given
        let company     = a.company.clone().context("--company is required (or supply --config)")?;
        let industry    = a.industry.clone().context("--industry is required (or supply --config)")?;
        let description = a.description.clone().context("--description is required (or supply --config)")?;
        StoryConfig::new(company, industry, description)
    };

    // CLI flags override whatever came from the YAML file
    if let Some(v) = a.company.clone()      { story.company_name  = v; }
    if let Some(v) = a.industry.clone()     { story.industry      = v; }
    if let Some(v) = a.description.clone()  { story.description   = v; }
    if let Some(v) = a.size.clone()         { story.company_size  = v; }
    if let Some(v) = a.num_users           { story.num_users      = v; }
    if let Some(v) = a.days               { story.duration_days  = v; }
    if let Some(v) = a.eval_batch_size    { story.eval_batch_size = v; }
    if !a.events.is_empty()               { story.key_events     = a.events.clone(); }

    // -----------------------------------------------------------------------
    // Print resolved config
    // -----------------------------------------------------------------------
    println!("EABench – Data Generation Pipeline (Rust)");
    println!("------------------------------------------");
    println!("Company        : {}", story.company_name);
    println!("Industry       : {}", story.industry);
    println!("Size           : {}", story.company_size);
    println!("Users          : {}", story.num_users);
    println!("Days           : {}", story.duration_days);
    println!("Eval batch     : {}", story.eval_batch_size);
    println!("Events         : {}", if story.key_events.is_empty() { "(none)".to_string() } else { story.key_events.join(", ") });
    println!("Description    : {}", story.description);
    println!("Output dir     : {}", a.output_dir);
    println!("Prompts        : {}", a.prompts_path);
    println!("Temperature    : {}", a.temperature);
    if a.dry_run {
        println!();
        println!("[dry-run] Configuration resolved OK. Exiting without calling the LLM.");
        return Ok(());
    }
    println!();

    // -----------------------------------------------------------------------
    // Resolve LLM provider
    // -----------------------------------------------------------------------
    // Priority: explicit --provider flag > presence of Azure env vars > OpenAI
    let effective_provider = a.provider
        .clone()
        .unwrap_or_else(|| {
            if a.azure_endpoint.is_some() || std::env::var("AZURE_OPENAI_API_KEY").is_ok() {
                "azure".to_string()
            } else {
                "openai".to_string()
            }
        });

    let llm: Box<dyn eabench_lib::generator::LLMProvider> = match effective_provider.as_str() {
        "azure" => {
            let key = a.api_key.clone()
                .or_else(|| std::env::var("AZURE_OPENAI_API_KEY").ok())
                .or_else(|| std::env::var("AZURE_API_KEY").ok())
                .context("Azure provider: supply --api-key or set AZURE_OPENAI_API_KEY")?;
            let endpoint = a.azure_endpoint.clone()
                .or_else(|| std::env::var("AZURE_OPENAI_ENDPOINT").ok())
                .or_else(|| std::env::var("AZURE_ENDPOINT").ok())
                .context("Azure provider: supply --azure-endpoint or set AZURE_OPENAI_ENDPOINT")?;
            let deployment = a.azure_deployment.clone()
                .or_else(|| a.model.clone())
                .or_else(|| std::env::var("AZURE_OPENAI_DEPLOYMENT_NAME").ok())
                .or_else(|| std::env::var("AZURE_DEPLOYMENT_NAME").ok())
                .unwrap_or_else(|| "gpt-4o".to_string());
            let api_version = a.api_version.clone()
                .or_else(|| std::env::var("AZURE_OPENAI_API_VERSION").ok())
                .or_else(|| std::env::var("AZURE_API_VERSION").ok())
                .unwrap_or_else(|| "2024-02-15-preview".to_string());
            println!("LLM provider   : Azure OpenAI");
            println!("  Endpoint     : {}", endpoint);
            println!("  Deployment   : {}", deployment);
            println!("  API version  : {}", api_version);
            Box::new(AzureOpenAIProvider::new(key, endpoint, deployment, api_version, a.temperature))
        }
        "openai" | _ => {
            let key = a.api_key.clone()
                .or_else(|| std::env::var("OPENAI_API_KEY").ok())
                .context("OpenAI provider: supply --api-key or set OPENAI_API_KEY")?;
            let base_url = a.base_url.clone()
                .or_else(|| std::env::var("OPENAI_BASE_URL").ok())
                .or_else(|| std::env::var("OPENAI_API_BASE").ok());
            let model = a.model.clone()
                .or_else(|| std::env::var("OPENAI_MODEL").ok())
                .unwrap_or_else(|| "gpt-4o".to_string());
            println!("LLM provider   : OpenAI");
            println!("  Model        : {}", model);
            if let Some(ref url) = base_url {
                println!("  Base URL     : {}", url);
            }
            Box::new(OpenAIProvider::new(key, base_url, model, a.temperature))
        }
    };

    println!();

    // -----------------------------------------------------------------------
    // Build DataGenerator and run the full pipeline
    // -----------------------------------------------------------------------
    let generator = DataGenerator::new(llm, &a.output_dir, &a.prompts_path)
        .context("Failed to initialise DataGenerator")?;

    println!("Starting generation…");
    let output = generator.generate_tenant(&story)
        .context("Data generation failed")?;

    println!();
    println!("Generation complete!");
    println!("{:-<60}", "");
    println!("Tenant ID    : {}", output.tenant_id);
    println!("Output path  : {}", output.base_path);
    println!("Summary      : {}", output.summary);
    println!("{:-<60}", "");

    Ok(())
}

// ---------------------------------------------------------------------------
// Argument parsing
// ---------------------------------------------------------------------------

fn parse_args(args: &[String]) -> Result<Command> {
    // Determine subcommand (first non-flag token, or default to "eval")
    let subcommand = args.get(1).map(|s| s.as_str()).unwrap_or("eval");

    match subcommand {
        "generate" => parse_generate_args(&args[2..]),
        "eval"     => parse_eval_args(&args[2..]),
        "serve"    => parse_serve_args(&args[2..]),
        "--help" | "-h" => {
            print_usage();
            std::process::exit(0);
        }
        // Backwards-compatible: if first arg looks like a flag, treat as eval
        _ if subcommand.starts_with('-') => parse_eval_args(&args[1..]),
        other => anyhow::bail!(
            "Unknown subcommand '{}'. Expected 'generate', 'eval', or 'serve'. Use --help for usage.",
            other
        ),
    }
}

fn parse_eval_args(args: &[String]) -> Result<Command> {
    let mut tenant_path  = PathBuf::from("examples/tenants/test-tenant-1/tenant.yaml");
    let mut eval_path    = PathBuf::from("examples/tenants/test-tenant-1/eval_set.yaml");
    let mut num_workers: usize = 0;

    // LLM provider
    let mut provider: Option<String>         = None;
    let mut model: Option<String>            = None;
    let mut api_key: Option<String>          = None;
    let mut base_url: Option<String>         = None;
    let mut azure_endpoint: Option<String>   = None;
    let mut azure_deployment: Option<String> = None;
    let mut api_version: Option<String>      = None;
    let mut temperature: f64                 = 0.0;

    // Agent / judge
    let mut agent_config_path: Option<PathBuf> = None;
    let mut judge_config_path = PathBuf::from("examples/evals/default_judge.yaml");
    let mut max_turns: usize = 6;

    let mut i = 0usize;
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
            // LLM provider flags
            "--provider" => {
                i += 1;
                let v = args.get(i).context("--provider requires openai|azure")?;
                match v.as_str() {
                    "openai" | "azure" => provider = Some(v.clone()),
                    other => anyhow::bail!("--provider must be 'openai' or 'azure' (got '{}')", other),
                }
            }
            "--model" => {
                i += 1;
                model = Some(args.get(i).context("--model requires a VALUE")?.clone());
            }
            "--api-key" => {
                i += 1;
                api_key = Some(args.get(i).context("--api-key requires a VALUE")?.clone());
            }
            "--base-url" => {
                i += 1;
                base_url = Some(args.get(i).context("--base-url requires a URL")?.clone());
            }
            "--azure-endpoint" => {
                i += 1;
                azure_endpoint = Some(args.get(i).context("--azure-endpoint requires a URL")?.clone());
            }
            "--azure-deployment" => {
                i += 1;
                azure_deployment = Some(args.get(i).context("--azure-deployment requires a VALUE")?.clone());
            }
            "--api-version" => {
                i += 1;
                api_version = Some(args.get(i).context("--api-version requires a VALUE")?.clone());
            }
            "--temperature" => {
                i += 1;
                let v = args.get(i).context("--temperature requires a FLOAT")?;
                temperature = v.parse::<f64>()
                    .with_context(|| format!("--temperature '{}' is not a valid float", v))?;
            }
            // Agent / judge flags
            "--agent-config" => {
                i += 1;
                agent_config_path = Some(PathBuf::from(
                    args.get(i).context("--agent-config requires a PATH")?,
                ));
            }
            "--judge-config" => {
                i += 1;
                judge_config_path = PathBuf::from(
                    args.get(i).context("--judge-config requires a PATH")?,
                );
            }
            "--max-turns" => {
                i += 1;
                let n = args.get(i).context("--max-turns requires a NUMBER")?;
                max_turns = n.parse::<usize>()
                    .with_context(|| format!("--max-turns '{}' is not a valid number", n))?;
            }
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            other => anyhow::bail!("Unknown argument '{}'. Use --help for usage.", other),
        }
        i += 1;
    }

    let agent_config_path = agent_config_path.map(resolve_path);

    Ok(Command::Eval(EvalArgs {
        tenant_path: resolve_path(tenant_path),
        eval_path:   resolve_path(eval_path),
        num_workers,
        provider,
        model,
        api_key,
        base_url,
        azure_endpoint,
        azure_deployment,
        api_version,
        temperature,
        agent_config_path,
        judge_config_path: resolve_path(judge_config_path),
        max_turns,
    }))
}

fn parse_generate_args(args: &[String]) -> Result<Command> {
    let mut config_file: Option<String>     = None;
    let mut company: Option<String>         = None;
    let mut industry: Option<String>        = None;
    let mut description: Option<String>     = None;
    let mut events: Vec<String>             = vec![];
    let mut size: Option<String>            = None;
    let mut num_users: Option<usize>        = None;
    let mut days: Option<usize>             = None;
    let mut eval_batch_size: Option<usize>  = None;
    let mut output_dir                      = "../examples/tenants".to_string();
    let mut prompts_path                    = "../examples/generation/default_prompts.yaml".to_string();

    // LLM provider flags
    let mut provider: Option<String>        = None;
    let mut model: Option<String>           = None;
    let mut api_key: Option<String>         = None;
    let mut base_url: Option<String>        = None;
    let mut azure_endpoint: Option<String>  = None;
    let mut azure_deployment: Option<String>= None;
    let mut api_version: Option<String>     = None;
    let mut temperature: f64               = 0.7;

    // Behaviour flags
    let mut dry_run = false;

    let mut i = 0usize;
    while i < args.len() {
        match args[i].as_str() {
            // ---- story config ----
            "--config" => {
                i += 1;
                config_file = Some(args.get(i).context("--config requires a FILE path")?.clone());
            }
            "--company" => {
                i += 1;
                company = Some(args.get(i).context("--company requires a VALUE")?.clone());
            }
            "--industry" => {
                i += 1;
                industry = Some(args.get(i).context("--industry requires a VALUE")?.clone());
            }
            "--description" => {
                i += 1;
                description = Some(args.get(i).context("--description requires a VALUE")?.clone());
            }
            "--events" => {
                i += 1;
                while i < args.len() && !args[i].starts_with('-') {
                    events.push(args[i].clone());
                    i += 1;
                }
                continue;
            }
            "--size" => {
                i += 1;
                let v = args.get(i).context("--size requires small|medium|large")?;
                match v.as_str() {
                    "small" | "medium" | "large" => size = Some(v.clone()),
                    other => anyhow::bail!("--size must be small, medium, or large (got '{}')", other),
                }
            }
            "--num-users" => {
                i += 1;
                let v = args.get(i).context("--num-users requires a NUMBER")?;
                let n = v.parse::<usize>()
                    .with_context(|| format!("--num-users '{}' is not a valid number", v))?;
                anyhow::ensure!(n >= 1 && n <= 100, "--num-users must be between 1 and 100");
                num_users = Some(n);
            }
            "--days" => {
                i += 1;
                let v = args.get(i).context("--days requires a NUMBER")?;
                let n = v.parse::<usize>()
                    .with_context(|| format!("--days '{}' is not a valid number", v))?;
                anyhow::ensure!(n >= 1 && n <= 365, "--days must be between 1 and 365");
                days = Some(n);
            }
            "--eval-batch-size" => {
                i += 1;
                let v = args.get(i).context("--eval-batch-size requires a NUMBER")?;
                eval_batch_size = Some(v.parse::<usize>()
                    .with_context(|| format!("--eval-batch-size '{}' is not valid", v))?);
            }
            // ---- output ----
            "--output" => {
                i += 1;
                output_dir = args.get(i).context("--output requires a PATH")?.clone();
            }
            "--prompts" => {
                i += 1;
                prompts_path = args.get(i).context("--prompts requires a PATH")?.clone();
            }
            // ---- LLM provider ----
            "--provider" => {
                i += 1;
                let v = args.get(i).context("--provider requires openai|azure")?;
                match v.as_str() {
                    "openai" | "azure" => provider = Some(v.clone()),
                    other => anyhow::bail!("--provider must be 'openai' or 'azure' (got '{}')", other),
                }
            }
            "--model" => {
                i += 1;
                model = Some(args.get(i).context("--model requires a VALUE")?.clone());
            }
            "--api-key" => {
                i += 1;
                api_key = Some(args.get(i).context("--api-key requires a VALUE")?.clone());
            }
            "--base-url" => {
                i += 1;
                base_url = Some(args.get(i).context("--base-url requires a URL")?.clone());
            }
            "--azure-endpoint" => {
                i += 1;
                azure_endpoint = Some(args.get(i).context("--azure-endpoint requires a URL")?.clone());
            }
            "--azure-deployment" => {
                i += 1;
                azure_deployment = Some(args.get(i).context("--azure-deployment requires a VALUE")?.clone());
            }
            "--api-version" => {
                i += 1;
                api_version = Some(args.get(i).context("--api-version requires a VALUE")?.clone());
            }
            "--temperature" => {
                i += 1;
                let v = args.get(i).context("--temperature requires a FLOAT")?;
                temperature = v.parse::<f64>()
                    .with_context(|| format!("--temperature '{}' is not a valid float", v))?;
                anyhow::ensure!((0.0..=2.0).contains(&temperature), "--temperature must be between 0.0 and 2.0");
            }
            // ---- behaviour ----
            "--dry-run" => { dry_run = true; }
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            other => anyhow::bail!("Unknown argument '{}'. Use --help for usage.", other),
        }
        i += 1;
    }

    // Validate: if no --config, the three mandatory story fields must be present
    if config_file.is_none() {
        if company.is_none()     { anyhow::bail!("--company is required (or supply --config)"); }
        if industry.is_none()    { anyhow::bail!("--industry is required (or supply --config)"); }
        if description.is_none() { anyhow::bail!("--description is required (or supply --config)"); }
    }

    // Resolve output_dir and prompts_path relative to repo root if needed
    let output_dir = resolve_path(PathBuf::from(&output_dir))
        .to_string_lossy().into_owned();
    let prompts_path = resolve_path(PathBuf::from(&prompts_path))
        .to_string_lossy().into_owned();

    Ok(Command::Generate(GenerateArgs {
        config_file,
        company,
        industry,
        description,
        events,
        size,
        num_users,
        days,
        eval_batch_size,
        output_dir,
        prompts_path,
        provider,
        model,
        api_key,
        base_url,
        azure_endpoint,
        azure_deployment,
        api_version,
        temperature,
        dry_run,
    }))
}

fn print_usage() {
    println!(
        "EABench – Agent Execution and Evaluation Platform (Rust)\n\
         \n\
         USAGE:\n\
         \x20   cargo run -- <SUBCOMMAND> [OPTIONS]\n\
         \n\
         SUBCOMMANDS:\n\
         \x20   eval      Run deterministic evaluation against an eval set (default)\n\
         \x20   generate  Generate a new synthetic tenant using an LLM\n\
         \x20   serve     Launch the Streamlit web UI\n\
         \n\
         ── EVAL: data ───────────────────────────────────────────────────\n\
         \x20   --tenant PATH           Path to tenant.yaml  (default: examples/tenants/test-tenant-1/tenant.yaml)\n\
         \x20   --eval   PATH           Path to eval YAML    (default: examples/tenants/test-tenant-1/eval_set.yaml)\n\
         \x20   --workers N             Parallel worker threads (default: 0 = auto)\n\
         \n\
         ── EVAL: LLM provider (same flags as generate) ──────────────────\n\
         \x20   --provider openai|azure   Force provider (default: auto-detect from env)\n\
         \x20   --model TEXT              Model / deployment name (overrides env var)\n\
         \x20   --api-key TEXT            API key (overrides env var)\n\
         \x20   --base-url URL            OpenAI: custom base URL\n\
         \x20   --azure-endpoint URL      Azure: endpoint URL\n\
         \x20   --azure-deployment TEXT   Azure: deployment name\n\
         \x20   --api-version TEXT        Azure: API version (default: 2024-02-15-preview)\n\
         \x20   --temperature FLOAT       Sampling temperature (default: 0.0)\n\
         \n\
         ── EVAL: agent / judge ──────────────────────────────────────────\n\
         \x20   --agent-config PATH   Path to agent YAML (optional; uses built-in default if omitted)\n\
         \x20   --judge-config PATH   Path to judge YAML (default: examples/evals/default_judge.yaml)\n\
         \x20   --max-turns N         Max ReAct agent turns per case (default: 6)\n\
         \n\
         ── GENERATE: story config ───────────────────────────────────────\n\
         \x20   --config FILE         Load StoryConfig from a YAML file (field flags below override it)\n\
         \x20   --company TEXT        Company name                         [required if no --config]\n\
         \x20   --industry TEXT       Industry vertical                    [required if no --config]\n\
         \x20   --description TEXT    Detailed scenario description        [required if no --config]\n\
         \x20   --events TEXT...      Key events, space-separated (e.g. \"Kickoff\" \"Q1 Review\")\n\
         \x20   --size TEXT           Company size: small|medium|large     (default: small)\n\
         \x20   --num-users N         Synthetic users to generate (1-100)  (default: 5)\n\
         \x20   --days N              Simulation duration in days (1-365)   (default: 7)\n\
         \x20   --eval-batch-size N   Eval generation batch size            (default: 5)\n\
         \n\
         ── GENERATE: output ─────────────────────────────────────────────\n\
         \x20   --output PATH         Root directory for generated tenants  (default: ../examples/tenants)\n\
         \x20   --prompts PATH        Path to prompts YAML                  (default: ../examples/generation/default_prompts.yaml)\n\
         \n\
         ── GENERATE: LLM provider ───────────────────────────────────────\n\
         \x20   --provider openai|azure   Force provider (default: auto-detect from env)\n\
         \x20   --model TEXT              Model / deployment name (overrides env var)\n\
         \x20   --api-key TEXT            API key (overrides env var)\n\
         \x20   --base-url URL            OpenAI: custom base URL (e.g. for local vLLM)\n\
         \x20   --azure-endpoint URL      Azure: endpoint URL\n\
         \x20   --azure-deployment TEXT   Azure: deployment name\n\
         \x20   --api-version TEXT        Azure: API version (default: 2024-02-15-preview)\n\
         \x20   --temperature FLOAT       Sampling temperature 0.0-2.0     (default: 0.7)\n\
         \n\
         ── GENERATE: behaviour ──────────────────────────────────────────\n\
         \x20   --dry-run             Print the resolved config and exit without calling the LLM\n\
         \n\
         ── GENERATE: env-var fallbacks ──────────────────────────────────\n\
         \x20   OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL / OPENAI_API_BASE\n\
         \x20   AZURE_OPENAI_API_KEY / AZURE_API_KEY\n\
         \x20   AZURE_OPENAI_ENDPOINT / AZURE_ENDPOINT\n\
         \x20   AZURE_OPENAI_DEPLOYMENT_NAME / AZURE_DEPLOYMENT_NAME\n\
         \x20   AZURE_OPENAI_API_VERSION / AZURE_API_VERSION\n\
         \n\
         ── SERVE ────────────────────────────────────────────────────────\n\
         \x20   --port N      Port for the Streamlit server  (default: 8501)\n\
         \x20   --app  PATH   Path to app.py                 (default: ../app.py)\n\
         \n\
         \x20   --help               Print this message\n"
    );
}

fn parse_serve_args(args: &[String]) -> Result<Command> {
    let mut port: u16 = 8501;
    let mut app       = "../python/app.py".to_string();

    let mut i = 0usize;
    while i < args.len() {
        match args[i].as_str() {
            "--port" => {
                i += 1;
                let v = args.get(i).context("--port requires a NUMBER")?;
                port = v.parse::<u16>()
                    .with_context(|| format!("--port '{}' is not a valid port number", v))?;
            }
            "--app" => {
                i += 1;
                app = args.get(i).context("--app requires a PATH")?.clone();
            }
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            other => anyhow::bail!("Unknown argument '{}'. Use --help for usage.", other),
        }
        i += 1;
    }

    let app = resolve_path(PathBuf::from(&app)).to_string_lossy().into_owned();
    Ok(Command::Serve(ServeArgs { port, app }))
}
