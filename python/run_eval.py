"""
EABench Python Evaluation CLI

Runs the agent against an eval dataset and saves per-case metrics + a summary.

Usage (from repo root):
    cd python
    python run_eval.py \\
        --tenant  ../examples/tenants/my-tenant/tenant.yaml \\
        --eval    ../examples/tenants/my-tenant/eval_dataset_*.yaml \\
        --agent   ../examples/agents/react_agent_v2.yaml \\
        --judge   ../examples/evals/default_judge.yaml \\
        --output  results/eval_results.json
"""

import asyncio
import argparse
import json
import os
from datetime import datetime, timezone
from typing import Optional

import yaml
from dotenv import load_dotenv

from src.config.agent_config import AgentConfig, ProviderType
from src.config.tenant_config import TenantConfig
from src.core.agent_runner import AgentRunner
from src.core.openai_provider import OpenAIProvider
from src.core.azure_provider import AzureOpenAIProvider
from src.core.provider_factory import build_resources
from src.core.search_engine import SearchEngine
from src.core.tool_registry import registry
from src.sandbox.local_sandbox import LocalSandbox
from src.eval.evaluator import Evaluator
from src.eval.models import EvaluationSet
import src.core.tools  # register tools side-effectfully


# ---------------------------------------------------------------------------
# CLI-specific LLM factory (supports --model / --api-key / --provider overrides)
# ---------------------------------------------------------------------------

def _build_llm(provider: str, model: Optional[str], api_key: Optional[str],
               base_url: Optional[str], azure_endpoint: Optional[str],
               azure_deployment: Optional[str], api_version: Optional[str],
               temperature: float):
    """Resolve the effective LLM provider from CLI overrides + env vars."""
    effective = provider or (
        "azure"
        if (azure_endpoint or os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY"))
        else "openai"
    )

    if effective == "azure":
        key = (api_key
               or os.getenv("AZURE_OPENAI_API_KEY")
               or os.getenv("AZURE_API_KEY"))
        endpoint = (azure_endpoint
                    or os.getenv("AZURE_OPENAI_ENDPOINT")
                    or os.getenv("AZURE_ENDPOINT"))
        deployment = (azure_deployment
                      or model
                      or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
                      or os.getenv("AZURE_DEPLOYMENT_NAME"))
        ver = (api_version
               or os.getenv("AZURE_OPENAI_API_VERSION")
               or os.getenv("AZURE_API_VERSION")
               or "2024-02-15-preview")
        if not key:
            raise SystemExit("Azure provider: supply --api-key or set AZURE_OPENAI_API_KEY")
        if not endpoint:
            raise SystemExit("Azure provider: supply --azure-endpoint or set AZURE_OPENAI_ENDPOINT")
        print(f"LLM provider    : Azure OpenAI")
        print(f"  Endpoint      : {endpoint}")
        print(f"  Deployment    : {deployment}")
        print(f"  API version   : {ver}")
        return AzureOpenAIProvider(
            api_key=key,
            azure_endpoint=endpoint,
            deployment_name=deployment,
            api_version=ver,
            temperature=temperature,
        )
    else:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise SystemExit("OpenAI provider: supply --api-key or set OPENAI_API_KEY")
        resolved_model = model or os.getenv("OPENAI_MODEL", "gpt-4o")
        resolved_base_url = (base_url
                             or os.getenv("OPENAI_BASE_URL")
                             or os.getenv("OPENAI_API_BASE"))
        print(f"LLM provider    : OpenAI  (model: {resolved_model})")
        return OpenAIProvider(
            api_key=key,
            base_url=resolved_base_url,
            model=resolved_model,
            temperature=temperature,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Run EABench evaluation against an eval dataset and save metrics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_eval.py \\
      --tenant  ../examples/tenants/my-tenant/tenant.yaml \\
      --eval    ../examples/tenants/my-tenant/eval_dataset.yaml

  python run_eval.py \\
      --tenant  ../examples/tenants/my-tenant/tenant.yaml \\
      --eval    ../examples/tenants/my-tenant/eval_dataset.yaml \\
      --agent   ../examples/agents/react_agent_v2.yaml \\
      --judge   ../examples/evals/default_judge.yaml \\
      --output  results/report.json \\
      --provider azure
""",
    )

    # Required paths
    parser.add_argument("--tenant", required=True,
                        help="Path to tenant.yaml")
    parser.add_argument("--eval", required=True, dest="eval_path",
                        help="Path to eval dataset YAML")

    # Optional paths (sensible defaults)
    parser.add_argument("--agent", default="../examples/agents/react_agent_v2.yaml",
                        help="Path to agent config YAML  (default: ../examples/agents/react_agent_v2.yaml)")
    parser.add_argument("--judge", default="../examples/evals/default_judge.yaml",
                        help="Path to judge prompts YAML  (default: ../examples/evals/default_judge.yaml)")
    parser.add_argument("--output", default=None,
                        help="Output JSON file path  (default: auto-named under results/)")

    # LLM provider overrides (all optional – fall back to env vars)
    parser.add_argument("--provider", choices=["openai", "azure"], default=None,
                        help="Force LLM provider  (default: auto-detect from env)")
    parser.add_argument("--model", default=None,
                        help="Model / deployment name  (overrides env var)")
    parser.add_argument("--api-key", dest="api_key", default=None,
                        help="API key  (overrides env var)")
    parser.add_argument("--base-url", dest="base_url", default=None,
                        help="OpenAI: custom base URL")
    parser.add_argument("--azure-endpoint", dest="azure_endpoint", default=None,
                        help="Azure: endpoint URL")
    parser.add_argument("--azure-deployment", dest="azure_deployment", default=None,
                        help="Azure: deployment name")
    parser.add_argument("--api-version", dest="api_version", default=None,
                        help="Azure: API version  (default: 2024-02-15-preview)")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="LLM temperature for judge  (default: 0.0)")

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Validate input files
    # ------------------------------------------------------------------
    for label, path in [("--tenant", args.tenant),
                         ("--eval", args.eval_path),
                         ("--agent", args.agent),
                         ("--judge", args.judge)]:
        if not os.path.exists(path):
            raise SystemExit(f"File not found for {label}: {path}")

    # ------------------------------------------------------------------
    # Load configs
    # ------------------------------------------------------------------
    print("=" * 60)
    print("EABench Evaluation")
    print("=" * 60)
    print(f"Tenant config   : {args.tenant}")
    print(f"Eval set        : {args.eval_path}")
    print(f"Agent config    : {args.agent}")
    print(f"Judge config    : {args.judge}")

    tenant_config = TenantConfig.from_yaml(args.tenant)
    agent_config = AgentConfig.from_yaml(args.agent)

    with open(args.eval_path, "r") as f:
        eval_set = EvaluationSet.model_validate(yaml.safe_load(f))

    with open(args.judge, "r") as f:
        judge_cfg = yaml.safe_load(f)
    judge_prompts: dict = judge_cfg.get("prompts", {})

    print(f"\nTenant          : {tenant_config.id}")
    print(f"Eval set        : {eval_set.name}  ({len(eval_set.cases)} cases)")

    # ------------------------------------------------------------------
    # Build LLM provider (for both agent and judge)
    # ------------------------------------------------------------------
    llm = _build_llm(
        provider=args.provider,
        # If --model not given, use deployment name from the agent config YAML
        model=args.model or agent_config.model.name,
        api_key=args.api_key,
        base_url=args.base_url,
        azure_endpoint=args.azure_endpoint,
        azure_deployment=args.azure_deployment,
        api_version=args.api_version,
        temperature=args.temperature,
    )

    # ------------------------------------------------------------------
    # Build embedding provider, sandbox, search engine, agent runner
    # (LLM already built above; pass it in so build_resources skips re-building it)
    # ------------------------------------------------------------------
    try:
        llm, _embedding, sandbox, search_engine = build_resources(agent_config, tenant_config, llm=llm)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    runner = AgentRunner(agent_config, llm, registry)

    # ------------------------------------------------------------------
    # Index tenant data into the search engine
    # ------------------------------------------------------------------
    print("\nIndexing tenant data …")
    await search_engine.index_all()
    print("Indexing complete.\n")

    # ------------------------------------------------------------------
    # Run evaluation
    # ------------------------------------------------------------------
    evaluator = Evaluator(
        runner=runner,
        llm=llm,
        sandbox=sandbox,
        search_engine=search_engine,
        prompts=judge_prompts,
    )

    print(f"\nRunning {len(eval_set.cases)} cases …\n")
    results = await evaluator.evaluate_batch(eval_set)

    # ------------------------------------------------------------------
    # Compute summary statistics
    # ------------------------------------------------------------------
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    assertion_scores = [r.metrics.get("assertion_score", 0.0) for r in results]
    citation_scores = [r.metrics.get("citation_score", 0.0) for r in results]
    tool_citation_scores = [r.metrics.get("tool_citation_score", 0.0) for r in results]
    response_citation_scores = [r.metrics.get("response_citation_score", 0.0) for r in results]
    # 4 explicit scorecard metrics
    tool_search_result_numbers = [r.metrics.get("tool_search_result_number", 0) for r in results]
    tool_search_result_relevances = [r.metrics.get("tool_search_result_relevance", 0.0) for r in results]
    response_citation_numbers = [r.metrics.get("response_citation_number", 0) for r in results]
    response_citation_relevances = [r.metrics.get("response_citation_relevance", 0.0) for r in results]
    mean_assertion = sum(assertion_scores) / total if total else 0.0
    mean_citation = sum(citation_scores) / total if total else 0.0
    mean_tool_citation = sum(tool_citation_scores) / total if total else 0.0
    mean_response_citation = sum(response_citation_scores) / total if total else 0.0
    mean_tool_search_result_number = sum(tool_search_result_numbers) / total if total else 0.0
    mean_tool_search_result_relevance = sum(tool_search_result_relevances) / total if total else 0.0
    mean_response_citation_number = sum(response_citation_numbers) / total if total else 0.0
    mean_response_citation_relevance = sum(response_citation_relevances) / total if total else 0.0

    # ------------------------------------------------------------------
    # Print summary
    # ------------------------------------------------------------------
    print()
    print("=" * 72)
    print("Results")
    print("=" * 72)
    hdr = f"{'Case ID':<30}  {'assert':>6}  {'srch#':>5}  {'srch_rel':>8}  {'cite#':>5}  {'cite_rel':>8}  {'pass':>4}"
    print(hdr)
    print("-" * 72)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        ascore  = r.metrics.get("assertion_score", 0.0)
        srch_n  = r.metrics.get("tool_search_result_number", 0)
        srch_r  = r.metrics.get("tool_search_result_relevance", 0.0)
        cite_n  = r.metrics.get("response_citation_number", 0)
        cite_r  = r.metrics.get("response_citation_relevance", 0.0)
        print(f"{r.case_id:<30}  {ascore:>6.2f}  {srch_n:>5}  {srch_r:>8.2f}  {cite_n:>5}  {cite_r:>8.2f}  {status:>4}")

    print("-" * 72)
    print(f"Pass rate       : {passed}/{total} ({100 * passed / total:.1f}%)" if total else "No cases.")
    print(f"Mean assertion  : {mean_assertion:.3f}")
    print()
    print("Scorecard (averages):")
    print(f"  tool_search_result_number    : {mean_tool_search_result_number:.2f}")
    print(f"  tool_search_result_relevance : {mean_tool_search_result_relevance:.3f}")
    print(f"  response_citation_number     : {mean_response_citation_number:.2f}")
    print(f"  response_citation_relevance  : {mean_response_citation_relevance:.3f}")
    print("=" * 72)

    # ------------------------------------------------------------------
    # Persist full results to JSON
    # ------------------------------------------------------------------
    if args.output is None:
        os.makedirs("results", exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tenant_id = os.path.basename(os.path.dirname(args.tenant))
        args.output = f"results/eval_{tenant_id}_{ts}.json"

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    output_data = {
        "metadata": {
            "tenant": args.tenant,
            "eval_set": args.eval_path,
            "agent_config": args.agent,
            "judge_config": args.judge,
            "eval_set_name": eval_set.name,
            "total_cases": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total": total,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "mean_assertion_score": round(mean_assertion, 4),
            "mean_citation_score": round(mean_citation, 4),
            "mean_tool_citation_score": round(mean_tool_citation, 4),
            "mean_response_citation_score": round(mean_response_citation, 4),
            # 4 scorecard metrics
            "mean_tool_search_result_number": round(mean_tool_search_result_number, 2),
            "mean_tool_search_result_relevance": round(mean_tool_search_result_relevance, 4),
            "mean_response_citation_number": round(mean_response_citation_number, 2),
            "mean_response_citation_relevance": round(mean_response_citation_relevance, 4),
        },
        "cases": [r.model_dump() for r in results],
    }

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2, default=str)

    print(f"\nResults saved   : {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
