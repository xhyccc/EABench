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

use eabench_lib::config::TenantConfig;
use eabench_lib::eval::{Evaluator, EvaluationSet};
use eabench_lib::search::SearchEngine;
use eabench_lib::generator::{DataGenerator, StoryConfig, OpenAIProvider, AzureOpenAIProvider};

// ---------------------------------------------------------------------------
// Subcommand enum
// ---------------------------------------------------------------------------

enum Command {
    Eval(EvalArgs),
    Generate(GenerateArgs),
}

struct EvalArgs {
    tenant_path: PathBuf,
    eval_path: PathBuf,
    num_workers: usize,
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
// main
// ---------------------------------------------------------------------------

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();

    match parse_args(&args)? {
        Command::Eval(a)     => run_eval(a),
        Command::Generate(a) => run_generate(a),
    }
}

// ---------------------------------------------------------------------------
// eval subcommand
// ---------------------------------------------------------------------------

fn run_eval(a: EvalArgs) -> Result<()> {
    println!("EABench – Agent Execution and Evaluation Platform (Rust)");
    println!("----------------------------------------------------------");
    println!("Tenant config : {}", a.tenant_path.display());
    println!("Eval set      : {}", a.eval_path.display());
    println!(
        "Workers       : {}",
        if a.num_workers == 0 { "auto (logical CPU count)".to_string() } else { a.num_workers.to_string() }
    );
    println!();

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
    println!();

    let search_engine = SearchEngine::new(tenant.clone());

    println!(
        "Running evaluation with {} worker(s)…",
        if a.num_workers == 0 { "auto".to_string() } else { a.num_workers.to_string() }
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
        a.num_workers,
    );

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
        "--help" | "-h" => {
            print_usage();
            std::process::exit(0);
        }
        // Backwards-compatible: if first arg looks like a flag, treat as eval
        _ if subcommand.starts_with('-') => parse_eval_args(&args[1..]),
        other => anyhow::bail!(
            "Unknown subcommand '{}'. Expected 'generate' or 'eval'. Use --help for usage.",
            other
        ),
    }
}

fn parse_eval_args(args: &[String]) -> Result<Command> {
    let mut tenant_path = PathBuf::from("examples/tenants/test-tenant-1/tenant.yaml");
    let mut eval_path   = PathBuf::from("examples/tenants/test-tenant-1/eval_set.yaml");
    let mut num_workers: usize = 0;

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
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            other => anyhow::bail!("Unknown argument '{}'. Use --help for usage.", other),
        }
        i += 1;
    }

    Ok(Command::Eval(EvalArgs { tenant_path, eval_path, num_workers }))
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
         \n\
         ── EVAL ────────────────────────────────────────────────────────\n\
         \x20   --tenant PATH    Path to tenant.yaml  (default: examples/tenants/test-tenant-1/tenant.yaml)\n\
         \x20   --eval   PATH    Path to eval YAML    (default: examples/tenants/test-tenant-1/eval_set.yaml)\n\
         \x20   --workers N      Parallel worker threads (default: 0 = auto)\n\
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
         \x20   --help               Print this message\n"
    );
}
