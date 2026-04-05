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
from src.core.embedding_provider import AzureEmbeddingProvider, MockEmbeddingProvider
from src.core.search_engine import SearchEngine
from src.core.tool_registry import registry
from src.sandbox.local_sandbox import LocalSandbox
from src.eval.evaluator import Evaluator
from src.eval.models import EvaluationSet
import src.core.tools  # register tools side-effectfully


# ---------------------------------------------------------------------------
# Provider factory helpers
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


def _build_embedding(agent_config: AgentConfig):
    """Build embedding provider from agent config + env vars."""
    emb_cfg = agent_config.embedding
    if emb_cfg and emb_cfg.provider == ProviderType.AZURE:
        key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_ENDPOINT")
        ver = (os.getenv("AZURE_EMB_API_VERSION")
               or os.getenv("AZURE_OPENAI_API_VERSION")
               or os.getenv("AZURE_API_VERSION")
               or "2024-02-15-preview")
        if key and endpoint:
            return AzureEmbeddingProvider(
                api_key=key,
                azure_endpoint=endpoint,
                api_version=ver,
                deployment_name=emb_cfg.model,
            )
    return MockEmbeddingProvider()


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
        model=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        azure_endpoint=args.azure_endpoint,
        azure_deployment=args.azure_deployment,
        api_version=args.api_version,
        temperature=args.temperature,
    )

    # ------------------------------------------------------------------
    # Build embedding provider, sandbox, search engine, agent runner
    # ------------------------------------------------------------------
    embedding_provider = _build_embedding(agent_config)
    sandbox = LocalSandbox(tenant_config)
    search_engine = SearchEngine(tenant_config, embedding_provider, sandbox)
    runner = AgentRunner(agent_config, llm, registry)

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
    mean_assertion = sum(assertion_scores) / total if total else 0.0
    mean_citation = sum(citation_scores) / total if total else 0.0

    # ------------------------------------------------------------------
    # Print summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Results")
    print("=" * 60)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        ascore = r.metrics.get("assertion_score", 0.0)
        cscore = r.metrics.get("citation_score", 0.0)
        print(f"[{status}] {r.case_id:<30}  assertion={ascore:.2f}  citation={cscore:.2f}")

    print("-" * 60)
    print(f"Pass rate       : {passed}/{total} ({100 * passed / total:.1f}%)" if total else "No cases.")
    print(f"Mean assertion  : {mean_assertion:.3f}")
    print(f"Mean citation   : {mean_citation:.3f}")
    print("=" * 60)

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
        },
        "cases": [r.model_dump() for r in results],
    }

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2, default=str)

    print(f"\nResults saved   : {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
