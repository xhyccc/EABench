#!/usr/bin/env python3
"""
Post-hoc analyses over existing EABench eval JSON files.

No new LLM calls. Implements revision_plan.md items C4 (CI + significance),
C6 (threshold sensitivity), and B8 (cost breakdown). Also produces
stratified samples for C2 human-annotation study.

Inputs :  python/results/eval_{tenant}_{yyyymmdd_HHMMSS}.json
Outputs:  analyze/output/missing_experiments/*.csv + *.md

Usage:
    python scripts/analyze_post_hoc.py --mode all
    python scripts/analyze_post_hoc.py --mode ci-significance
    python scripts/analyze_post_hoc.py --mode threshold-sensitivity
    python scripts/analyze_post_hoc.py --mode cost
    python scripts/analyze_post_hoc.py --mode sample-for-annotation \
        --tenant bertrand-and-co.-20260407 --per-type 50
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
from collections import defaultdict
from pathlib import Path

try:
    from scipy.stats import wilcoxon, spearmanr  # type: ignore
except ImportError:  # pragma: no cover
    wilcoxon = None
    spearmanr = None

REPO = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO / "python" / "results"
OUT_DIR = REPO / "analyze" / "output" / "missing_experiments"

# Azure list prices (USD per 1M tokens) as of 2025-Q1; update before publishing.
PRICES = {
    "gpt-4o":        {"in": 2.50,  "out": 10.00},
    "gpt-4o-mini":   {"in": 0.15,  "out": 0.60},
}

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

# Map agent config filename → short name used in analysis.
AGENT_CONFIG_MAP = {
    "react_agent.yaml":       "react_v1",
    "react_agent_v2.yaml":    "react_v2",
    "researcher_agent.yaml":  "researcher",
    "react_agent_v3.yaml":    "react_v3",
    "retrieval_baseline.yaml": "baseline",
}


def load_all_results() -> dict[str, dict[str, dict]]:
    """Return {agent_name: {tenant_id: doc}} by reading metadata.agent_config.
    For multiple runs of the same (agent, tenant) keeps the latest by timestamp."""
    results: dict[str, dict[str, dict]] = defaultdict(dict)
    latest_ts: dict[tuple, str] = {}
    for p in sorted(RESULTS_DIR.glob("eval_*.json")):
        if "glmjudge" in p.name:
            continue
        try:
            doc = json.loads(p.read_text())
        except Exception:
            continue
        meta = doc.get("metadata", {})
        agent_cfg = Path(meta.get("agent_config", "")).name
        agent = AGENT_CONFIG_MAP.get(agent_cfg)
        if agent is None:
            continue
        m = re.search(r"tenants/([^/]+)/", str(meta.get("tenant", "")))
        if not m:
            continue
        tenant = m.group(1)
        ts = meta.get("timestamp", p.name)
        key = (agent, tenant)
        if key not in latest_ts or ts > latest_ts[key]:
            latest_ts[key] = ts
            results[agent][tenant] = doc
    return dict(results)

# ---------------------------------------------------------------------------
# C4 — Wilson 95 % CI + paired Wilcoxon
# ---------------------------------------------------------------------------

def wilson_ci(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = passed / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def ci_significance(results_by_agent: dict[str, dict[str, dict]], out: Path) -> None:
    """results_by_agent = {agent_name: {tenant: json}}"""
    rows = []
    for agent, per_tenant in results_by_agent.items():
        for tenant, doc in per_tenant.items():
            summary = doc.get("summary", {})
            total = summary.get("total", 0)
            passed = summary.get("passed", 0)
            lo, hi = wilson_ci(passed, total)
            rows.append({
                "agent": agent, "tenant": tenant, "n": total,
                "pass_rate": round(passed / total, 4) if total else 0.0,
                "ci95_lo": round(lo, 4), "ci95_hi": round(hi, 4),
                "mean_assertion": summary.get("mean_assertion_score", 0.0),
                "mean_rc_rel":    summary.get("mean_response_citation_relevance", 0.0),
            })

    csv_path = out / "c4_pass_rates_ci.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["agent"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {csv_path.relative_to(REPO)}  ({len(rows)} cells)")

    if wilcoxon is None:
        print("  scipy not installed — skipping Wilcoxon tests")
        return

    # Pairwise Wilcoxon on per-case pass/fail, matched by case_id within tenant.
    pairwise_rows = []
    agents = list(results_by_agent.keys())
    for i, a in enumerate(agents):
        for b in agents[i + 1:]:
            for tenant in results_by_agent[a].keys() & results_by_agent[b].keys():
                ca = {c["case_id"]: int(c["passed"]) for c in results_by_agent[a][tenant].get("cases", [])}
                cb = {c["case_id"]: int(c["passed"]) for c in results_by_agent[b][tenant].get("cases", [])}
                shared = sorted(ca.keys() & cb.keys())
                if len(shared) < 10:
                    continue
                xa = [ca[k] for k in shared]
                xb = [cb[k] for k in shared]
                if all(x == y for x, y in zip(xa, xb)):
                    stat, p = 0.0, 1.0
                else:
                    try:
                        stat, p = wilcoxon(xa, xb, zero_method="wilcox", alternative="two-sided")
                    except ValueError:
                        stat, p = 0.0, 1.0
                pairwise_rows.append({
                    "agent_a": a, "agent_b": b, "tenant": tenant,
                    "n_matched": len(shared),
                    "pass_a": round(sum(xa) / len(xa), 4),
                    "pass_b": round(sum(xb) / len(xb), 4),
                    "wilcoxon_stat": round(float(stat), 4),
                    "p_value": round(float(p), 6),
                })

    pw_path = out / "c4_pairwise_wilcoxon.csv"
    with pw_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(pairwise_rows[0].keys()) if pairwise_rows else ["agent_a"])
        writer.writeheader()
        writer.writerows(pairwise_rows)
    print(f"  wrote {pw_path.relative_to(REPO)}  ({len(pairwise_rows)} comparisons)")

# ---------------------------------------------------------------------------
# C6 — Threshold sensitivity
# ---------------------------------------------------------------------------

def threshold_sensitivity(results_by_agent: dict[str, dict[str, dict]], out: Path) -> None:
    taus = [0.70, 0.75, 0.80, 0.90, 1.00]
    rc_gate = 0.70
    rows = []
    for agent, per_tenant in results_by_agent.items():
        for tenant, doc in per_tenant.items():
            cases = doc.get("cases", [])
            if not cases:
                continue
            for tau in taus:
                passed = 0
                for c in cases:
                    m = c.get("metrics", {})
                    if (m.get("assertion_score", 0.0) >= tau and
                            m.get("response_citation_relevance", 0.0) >= rc_gate):
                        passed += 1
                rows.append({
                    "agent": agent, "tenant": tenant, "tau_assertion": tau,
                    "rc_gate": rc_gate, "n": len(cases),
                    "pass_rate": round(passed / len(cases), 4),
                })

    csv_path = out / "c6_threshold_sensitivity.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["agent"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {csv_path.relative_to(REPO)}  ({len(rows)} rows)")

# ---------------------------------------------------------------------------
# B8 — Cost breakdown
# ---------------------------------------------------------------------------

def _price(tokens_in: float, tokens_out: float, model: str) -> float:
    p = PRICES.get(model, PRICES["gpt-4o"])
    return tokens_in / 1_000_000 * p["in"] + tokens_out / 1_000_000 * p["out"]


def cost_breakdown(results_by_agent: dict[str, dict[str, dict]],
                    out: Path,
                    agent_models: dict[str, str]) -> None:
    judge_model = "gpt-4o"
    rows = []
    for agent, per_tenant in results_by_agent.items():
        amodel = agent_models.get(agent, "gpt-4o")
        for tenant, doc in per_tenant.items():
            cases = doc.get("cases", [])
            n = len(cases)
            if n == 0:
                continue
            # Tokens are stored in c["metrics"] by the agent runner.
            agent_in  = sum(c.get("metrics", {}).get("total_prompt_tokens", 0) for c in cases)
            agent_out = sum(c.get("metrics", {}).get("total_completion_tokens", 0) for c in cases)
            # Judge token counts are not stored per-case; estimate from
            # typical judge call size (3 assertions × ~800 prompt + ~80 output).
            mean_assertions = sum(
                len(c.get("assertion_results") or c.get("assertions") or [])
                for c in cases
            ) / max(len(cases), 1)
            judge_in  = int(mean_assertions * 800 * len(cases))
            judge_out = int(mean_assertions * 80  * len(cases))
            agent_cost = _price(agent_in, agent_out, amodel)
            judge_cost = _price(judge_in, judge_out, judge_model)
            rows.append({
                "agent": agent, "tenant": tenant, "n": n,
                "agent_model": amodel,
                "agent_in": agent_in, "agent_out": agent_out,
                "judge_in": judge_in, "judge_out": judge_out,
                "agent_usd": round(agent_cost, 4),
                "judge_usd": round(judge_cost, 4),
                "total_usd": round(agent_cost + judge_cost, 4),
                "usd_per_100_cases": round((agent_cost + judge_cost) / n * 100, 4),
            })
    csv_path = out / "b8_cost_breakdown.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["agent"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {csv_path.relative_to(REPO)}  ({len(rows)} rows)")

# ---------------------------------------------------------------------------
# C2 — Stratified annotation sample
# ---------------------------------------------------------------------------

def _infer_query_type(query: str) -> str:
    """Rule-based query type from keywords in the query text."""
    q = query.lower()
    is_email   = any(w in q for w in ["email", "sent", "wrote", "received", "inbox", "message i"])
    is_chat    = any(w in q for w in ["chat", "slack", "dm", "group chat", "channel"])
    is_meeting = any(w in q for w in ["meeting", "call", "transcript", "agenda", "discussed in"])
    is_file    = any(w in q for w in ["file", "document", "report", "spreadsheet", "pdf", "doc"])
    n = sum([is_email, is_chat, is_meeting, is_file])
    if n > 1:    return "cross-source"
    if is_email: return "email"
    if is_chat:  return "chat"
    if is_meeting: return "meeting"
    if is_file:  return "file"
    return "other"


def sample_for_annotation(tenant: str, per_type: int, out: Path, seed: int = 20260417) -> None:
    # Use the most recent react_v1 (react_agent) result for sampling.
    all_paths = sorted(RESULTS_DIR.glob(f"eval_{tenant}_*.json"))
    all_paths = [p for p in all_paths if "glmjudge" not in p.name]
    # Prefer react_agent (react_v1) run; fall back to newest.
    react_paths = [p for p in all_paths
                   if AGENT_CONFIG_MAP.get(Path(
                       json.loads(p.read_text()).get("metadata", {}).get("agent_config", "")
                   ).name) == "react_v1"]
    chosen = react_paths[-1] if react_paths else (all_paths[-1] if all_paths else None)
    if chosen is None:
        raise SystemExit(f"No results for tenant {tenant}")
    doc = json.loads(chosen.read_text())
    by_type: dict[str, list] = defaultdict(list)
    for c in doc.get("cases", []):
        qtype = _infer_query_type(c.get("query", ""))
        by_type[qtype].append(c)
    rng = random.Random(seed)
    rows = []
    for qtype, items in by_type.items():
        rng.shuffle(items)
        for c in items[:per_type]:
            assertions = c.get("assertion_results") or c.get("assertions") or []
            for i, a in enumerate(assertions):
                if isinstance(a, str):
                    text = a
                else:
                    text = a.get("description") or a.get("text") or a.get("id", "")
                rows.append({
                    "case_id": c["case_id"], "query_type": qtype,
                    "assertion_index": i, "assertion": text,
                    "grounded_1yes_0no": "", "satisfiable_1yes_0no": "", "non_trivial_1yes_0no": "",
                })
    csv_path = out / f"c2_annotation_sample_{tenant}.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["case_id"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {csv_path.relative_to(REPO)}  ({len(rows)} assertions)")

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

AGENT_MODELS = {
    "react_v1":   "gpt-4o",
    "react_v2":   "gpt-4o",
    "researcher": "gpt-4o-mini",
    "react_v3":   "gpt-4o-mini",
    "baseline":   "gpt-4o-mini",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True,
                    choices=["all", "ci-significance", "threshold-sensitivity",
                             "cost", "sample-for-annotation"])
    ap.add_argument("--tenant", default="bertrand-and-co.-20260407",
                    help="Tenant filter for sample-for-annotation")
    ap.add_argument("--per-type", type=int, default=50)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results_by_agent = load_all_results()
    if not results_by_agent:
        raise SystemExit("No recognised result JSONs found in python/results/.")
    agents_found = sorted(results_by_agent)
    tenants_found = sorted({t for v in results_by_agent.values() for t in v})
    print(f"  agents : {agents_found}")
    print(f"  tenants: {tenants_found}")

    if args.mode in {"all", "ci-significance"}:
        print("[C4] CI + pairwise Wilcoxon")
        ci_significance(results_by_agent, OUT_DIR)
    if args.mode in {"all", "threshold-sensitivity"}:
        print("[C6] threshold sensitivity")
        threshold_sensitivity(results_by_agent, OUT_DIR)
    if args.mode in {"all", "cost"}:
        print("[B8] cost breakdown")
        cost_breakdown(results_by_agent, OUT_DIR, AGENT_MODELS)
    if args.mode == "sample-for-annotation":
        print(f"[C2] sample for annotation: {args.tenant}  per-type={args.per_type}")
        sample_for_annotation(args.tenant, args.per_type, OUT_DIR)


if __name__ == "__main__":
    main()
