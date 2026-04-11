"""
04_eval_analysis.py
===================
Evaluation-result analysis for EABench.

Answers two questions:
  1. How does agent configuration affect search relevance?
     (tool search results and final response citations)
  2. How does agent configuration affect assertion pass rates?

Additionally provides per-tenant breakdowns so that tenant difficulty can be
separated from agent-capability effects.

Metrics explained
-----------------
  pass_rate                   fraction of test cases where ALL assertions pass
  mean_assertion_score        average assertion-level score (partial credit)
  mean_tool_search_result_relevance   relevance of documents retrieved by tools
  mean_tool_search_result_number      mean number of tool results returned
  mean_response_citation_relevance    relevance of items cited in final response
  mean_response_citation_number       mean number of citations in final response
  mean_tool_citation_score            citation quality from tool search
  mean_response_citation_score        citation quality in response
  latency                     average per-case agent latency (seconds)
  total_prompt_tokens / total_completion_tokens

The script reads all JSON files from python/results/, parses metadata (tenant
name, agent id), and produces:
  - Summary tables (CSV)
  - Bar charts comparing agents per metric (grouped by tenant)
  - Heatmap: metric × agent × tenant
  - Scatter plots: assertion_score vs search relevance
  - Metric correlation matrix

Usage
-----
    python analyze/04_eval_analysis.py \
        --results-dir python/results \
        --output-dir  analyze/output/eval_analysis
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

METRIC_LABELS = {
    "pass_rate":                          "Pass Rate",
    "mean_assertion_score":               "Assertion Score",
    "mean_tool_search_result_relevance":  "Tool Search Relevance",
    "mean_tool_search_result_number":     "Tool Results (n)",
    "mean_response_citation_relevance":   "Response Citation Relevance",
    "mean_response_citation_number":      "Response Citations (n)",
    "mean_tool_citation_score":           "Tool Citation Score",
    "mean_response_citation_score":       "Response Citation Score",
    "mean_citation_score":                "Overall Citation Score",
}


def extract_agent_id(agent_path: str) -> str:
    """Extract agent id from a path like '../examples/agents/react_agent.yaml'."""
    stem = Path(agent_path).stem
    return stem


def extract_tenant_id(tenant_path: str) -> str:
    """Extract tenant id from a path like '../examples/tenants/foo-bar/tenant.yaml'."""
    return Path(tenant_path).parent.name


def load_results(results_dir: Path) -> pd.DataFrame:
    records = []
    for fname in sorted(os.listdir(results_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = results_dir / fname
        with open(fpath, encoding="utf-8") as fh:
            data = json.load(fh)

        meta = data.get("metadata", {})
        summary = data.get("summary", {})
        cases = data.get("cases", [])

        agent = extract_agent_id(meta.get("agent_config", ""))
        tenant = extract_tenant_id(meta.get("tenant", ""))
        timestamp = meta.get("timestamp", "")

        # Case-level metrics (mean over all cases)
        case_latencies = [c["metrics"].get("latency", np.nan) for c in cases if "metrics" in c]
        case_prompt_toks = [c["metrics"].get("total_prompt_tokens", np.nan) for c in cases if "metrics" in c]
        case_comp_toks = [c["metrics"].get("total_completion_tokens", np.nan) for c in cases if "metrics" in c]
        case_tool_calls = [c["metrics"].get("tool_calls_count", np.nan) for c in cases if "metrics" in c]

        rec = {
            "file": fname,
            "tenant": tenant,
            "agent": agent,
            "timestamp": timestamp,
            "total_cases": meta.get("total_cases", len(cases)),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
        }
        # Pull all summary metrics
        for key in METRIC_LABELS:
            rec[key] = summary.get(key, np.nan)

        rec["mean_latency"] = np.nanmean(case_latencies) if case_latencies else np.nan
        rec["mean_prompt_tokens"] = np.nanmean(case_prompt_toks) if case_prompt_toks else np.nan
        rec["mean_completion_tokens"] = np.nanmean(case_comp_toks) if case_comp_toks else np.nan
        rec["mean_tool_calls"] = np.nanmean(case_tool_calls) if case_tool_calls else np.nan

        records.append(rec)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Per-case breakdown for deeper analysis
# ---------------------------------------------------------------------------

def load_all_cases(results_dir: Path) -> pd.DataFrame:
    rows = []
    for fname in sorted(os.listdir(results_dir)):
        if not fname.endswith(".json"):
            continue
        with open(results_dir / fname, encoding="utf-8") as fh:
            data = json.load(fh)
        meta = data.get("metadata", {})
        agent = extract_agent_id(meta.get("agent_config", ""))
        tenant = extract_tenant_id(meta.get("tenant", ""))
        for c in data.get("cases", []):
            m = c.get("metrics", {})
            rows.append({
                "file": fname,
                "tenant": tenant,
                "agent": agent,
                "case_id": c.get("case_id", ""),
                "passed": int(c.get("passed", False)),
                "assertion_score": m.get("assertion_score", np.nan),
                "tool_search_relevance": m.get("tool_search_result_relevance", np.nan),
                "tool_search_n": m.get("tool_search_result_number", np.nan),
                "response_citation_relevance": m.get("response_citation_relevance", np.nan),
                "response_citation_n": m.get("response_citation_number", np.nan),
                "tool_citation_score": m.get("tool_citation_score", np.nan),
                "response_citation_score": m.get("response_citation_score", np.nan),
                "latency": m.get("latency", np.nan),
                "tool_calls_count": m.get("tool_calls_count", np.nan),
                "prompt_tokens": m.get("total_prompt_tokens", np.nan),
                "completion_tokens": m.get("total_completion_tokens", np.nan),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

PALETTE = {
    "react_agent":      "#4E79A7",
    "react_agent_v2":   "#F28E2B",
    "researcher_agent": "#59A14F",
}

def agent_color(agent: str) -> str:
    return PALETTE.get(agent, "#999999")


def plot_metric_by_agent_tenant(df: pd.DataFrame, metric: str,
                                title: str, out_path: Path):
    """Grouped bar chart: x=tenant, hue=agent, y=metric."""
    pivot = df.pivot_table(index="tenant", columns="agent",
                           values=metric, aggfunc="mean")
    if pivot.empty:
        return

    fig, ax = plt.subplots(figsize=(max(8, len(pivot) * 2), 5))
    pivot.plot(kind="bar", ax=ax,
               color=[agent_color(a) for a in pivot.columns],
               alpha=0.85, edgecolor="white")
    ax.set_xlabel("Tenant")
    ax.set_ylabel(METRIC_LABELS.get(metric, metric))
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.legend(title="Agent", fontsize=9)
    ax.tick_params(axis="x", rotation=30)
    # Add value labels
    for container in ax.containers:
        ax.bar_label(container, fmt="%.2f", fontsize=7, padding=2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_agent_radar(df: pd.DataFrame, out_path: Path):
    """Radar/spider chart comparing agents across key metrics."""
    metrics = [
        "pass_rate",
        "mean_assertion_score",
        "mean_tool_search_result_relevance",
        "mean_response_citation_relevance",
        "mean_tool_citation_score",
    ]
    agents = sorted(df["agent"].unique())
    labels = [METRIC_LABELS.get(m, m) for m in metrics]
    N = len(metrics)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8, 8),
                           subplot_kw={"polar": True})

    for agent in agents:
        sub = df[df["agent"] == agent]
        vals = [float(sub[m].mean()) for m in metrics]
        vals += vals[:1]
        ax.plot(angles, vals, lw=2, label=agent, color=agent_color(agent))
        ax.fill(angles, vals, alpha=0.15, color=agent_color(agent))

    ax.set_thetagrids(np.degrees(angles[:-1]), labels, fontsize=9)
    ax.set_ylim(0, 1)
    ax.set_title("Agent Comparison (averaged across tenants)",
                 fontsize=12, fontweight="bold", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_heatmap(df: pd.DataFrame, metrics: list[str],
                 title: str, out_path: Path):
    """Heatmap: rows = metric, columns = (tenant, agent)."""
    rows = []
    for _, row in df.iterrows():
        col_label = f"{row['tenant'].split('-')[0]}\n{row['agent']}"
        for m in metrics:
            rows.append({"col": col_label, "metric": METRIC_LABELS.get(m, m),
                         "value": row[m]})
    heat_df = pd.DataFrame(rows).pivot_table(
        index="metric", columns="col", values="value", aggfunc="mean")

    if heat_df.empty:
        return

    fig, ax = plt.subplots(figsize=(max(10, heat_df.shape[1] * 1.5),
                                    max(5, heat_df.shape[0] * 0.8)))
    sns.heatmap(heat_df, annot=True, fmt=".2f", cmap="YlOrRd",
                ax=ax, linewidths=0.5, cbar_kws={"shrink": 0.8})
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel("")
    ax.set_ylabel("")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_scatter_relevance_vs_assertion(case_df: pd.DataFrame, out_path: Path):
    """Scatter: x=tool_search_relevance, y=assertion_score, hue=agent."""
    agents = sorted(case_df["agent"].unique())
    fig, ax = plt.subplots(figsize=(9, 6))
    for agent in agents:
        sub = case_df[case_df["agent"] == agent].dropna(
            subset=["tool_search_relevance", "assertion_score"])
        ax.scatter(sub["tool_search_relevance"], sub["assertion_score"],
                   s=20, alpha=0.4, color=agent_color(agent), label=agent)
        # Trend line
        if len(sub) > 3:
            z = np.polyfit(sub["tool_search_relevance"], sub["assertion_score"], 1)
            x_line = np.linspace(sub["tool_search_relevance"].min(),
                                  sub["tool_search_relevance"].max(), 100)
            ax.plot(x_line, np.polyval(z, x_line),
                    color=agent_color(agent), lw=1.5)

    ax.set_xlabel("Tool Search Relevance")
    ax.set_ylabel("Assertion Score")
    ax.set_title("Tool Search Relevance vs Assertion Score (per case)",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_pass_rate_breakdown(df: pd.DataFrame, out_path: Path):
    """Stacked bar chart: passed vs failed per (tenant, agent)."""
    fig, ax = plt.subplots(figsize=(max(10, len(df) * 1.2), 5))
    x_labels = [f"{r['tenant'].split('-')[0]}\n{r['agent']}" for _, r in df.iterrows()]
    x = np.arange(len(df))
    passed = df["passed"].values
    failed = df["failed"].values
    ax.bar(x, passed, label="Passed", color="#59A14F", alpha=0.85)
    ax.bar(x, failed, bottom=passed, label="Failed", color="#E15759", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=8)
    ax.set_ylabel("Number of cases")
    ax.set_title("Passed vs Failed Cases per (Tenant × Agent)",
                 fontsize=11, fontweight="bold")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_correlation_matrix(case_df: pd.DataFrame, out_path: Path):
    """Pearson correlation matrix of all numeric case-level metrics."""
    numeric_cols = [
        "passed", "assertion_score", "tool_search_relevance", "tool_search_n",
        "response_citation_relevance", "response_citation_n",
        "tool_citation_score", "response_citation_score",
        "latency", "tool_calls_count",
    ]
    sub = case_df[numeric_cols].dropna(how="all")
    corr = sub.corr()

    fig, ax = plt.subplots(figsize=(10, 9))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="coolwarm",
                vmin=-1, vmax=1, ax=ax, mask=False,
                linewidths=0.5, square=True)
    ax.set_title("Case-level Metric Correlation Matrix",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_latency_boxplot(case_df: pd.DataFrame, out_path: Path):
    """Boxplot of case latency per agent."""
    agents = sorted(case_df["agent"].unique())
    data = [case_df[case_df["agent"] == a]["latency"].dropna().values
            for a in agents]
    colors = [agent_color(a) for a in agents]

    fig, ax = plt.subplots(figsize=(8, 5))
    bp = ax.boxplot(data, tick_labels=agents, patch_artist=True,
                    medianprops={"color": "black", "lw": 2})
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.8)

    ax.set_ylabel("Latency (seconds)")
    ax.set_title("Case Latency Distribution per Agent", fontsize=11, fontweight="bold")
    ax.tick_params(axis="x", rotation=15)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Ranking table
# ---------------------------------------------------------------------------

def build_ranking_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate metrics averaged across tenants, ranked by pass_rate descending.
    """
    group_cols = ["agent"]
    agg_metrics = list(METRIC_LABELS.keys()) + ["mean_latency", "mean_tool_calls",
                                                  "mean_prompt_tokens",
                                                  "mean_completion_tokens"]
    agg = df.groupby(group_cols)[agg_metrics].mean().reset_index()
    agg = agg.sort_values("pass_rate", ascending=False).reset_index(drop=True)
    agg.insert(0, "rank", agg.index + 1)
    return agg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Evaluation-result analysis for EABench.")
    parser.add_argument("--results-dir",
                        default=str(repo_root / "python" / "results"))
    parser.add_argument("--output-dir",
                        default=str(repo_root / "analyze" / "output" / "eval_analysis"))
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    out_dir = Path(args.output_dir)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)

    if not results_dir.exists():
        sys.exit(f"Results directory not found: {results_dir}")

    print("Loading evaluation results …")
    df = load_results(results_dir)
    case_df = load_all_cases(results_dir)

    print(f"  Loaded {len(df)} result files, {len(case_df)} individual cases")
    print(f"  Tenants : {sorted(df['tenant'].unique())}")
    print(f"  Agents  : {sorted(df['agent'].unique())}")

    # ---- Summary CSV -------------------------------------------------------
    df.to_csv(out_dir / "data" / "eval_summary.csv", index=False)
    case_df.to_csv(out_dir / "data" / "cases.csv", index=False)

    # ---- Global ranking table ----------------------------------------------
    ranking = build_ranking_table(df)
    ranking.to_csv(out_dir / "data" / "agent_ranking.csv", index=False)
    print("\n=== Agent Ranking (averaged across all tenants) ===")
    print(ranking[["rank", "agent", "pass_rate", "mean_assertion_score",
                   "mean_tool_search_result_relevance",
                   "mean_response_citation_relevance"]].to_string(index=False))

    # ---- Figures -----------------------------------------------------------
    fig_dir = out_dir / "figures"

    # 1. Pass rate per agent × tenant
    plot_metric_by_agent_tenant(df, "pass_rate",
        "Pass Rate by Agent and Tenant", fig_dir / "pass_rate_by_agent_tenant.png")

    # 2. Assertion score per agent × tenant
    plot_metric_by_agent_tenant(df, "mean_assertion_score",
        "Assertion Score by Agent and Tenant",
        fig_dir / "assertion_score_by_agent_tenant.png")

    # 3. Tool search relevance per agent × tenant
    plot_metric_by_agent_tenant(df, "mean_tool_search_result_relevance",
        "Tool Search Relevance by Agent and Tenant",
        fig_dir / "tool_search_relevance_by_agent_tenant.png")

    # 4. Response citation relevance per agent × tenant
    plot_metric_by_agent_tenant(df, "mean_response_citation_relevance",
        "Response Citation Relevance by Agent and Tenant",
        fig_dir / "response_citation_relevance_by_agent_tenant.png")

    # 5. Radar chart
    plot_agent_radar(df, fig_dir / "agent_radar.png")

    # 6. Heatmap of key metrics
    key_metrics = [
        "pass_rate", "mean_assertion_score",
        "mean_tool_search_result_relevance", "mean_response_citation_relevance",
        "mean_tool_citation_score",
    ]
    plot_heatmap(df, key_metrics,
                 "Key Metrics Heatmap (Tenant × Agent)",
                 fig_dir / "metrics_heatmap.png")

    # 7. Passed vs failed stacked bar
    plot_pass_rate_breakdown(df, fig_dir / "pass_fail_breakdown.png")

    # 8. Scatter: tool relevance vs assertion score
    plot_scatter_relevance_vs_assertion(case_df,
        fig_dir / "scatter_relevance_vs_assertion.png")

    # 9. Case-level correlation matrix
    plot_correlation_matrix(case_df, fig_dir / "correlation_matrix.png")

    # 10. Latency boxplot
    plot_latency_boxplot(case_df, fig_dir / "latency_boxplot.png")

    # 11. Per-tenant pass rate bar (all agents overlaid)
    for tenant in sorted(df["tenant"].unique()):
        sub = df[df["tenant"] == tenant].copy()
        if sub.empty:
            continue
        fig, ax = plt.subplots(figsize=(7, 4))
        agents = sorted(sub["agent"].unique())
        x = np.arange(len(agents))
        ax.bar(x, sub.set_index("agent").loc[agents]["pass_rate"].values,
               color=[agent_color(a) for a in agents], alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(agents, rotation=20)
        ax.set_ylabel("Pass Rate")
        ax.set_ylim(0, 1)
        ax.set_title(f"Pass Rate by Agent — {tenant}", fontsize=10, fontweight="bold")
        for i, a in enumerate(agents):
            val = sub[sub["agent"] == a]["pass_rate"].values[0]
            ax.text(i, val + 0.01, f"{val:.3f}", ha="center", fontsize=9)
        fig.tight_layout()
        safe_tenant = re.sub(r"[^a-zA-Z0-9_-]", "_", tenant)
        fig.savefig(fig_dir / f"{safe_tenant}_pass_rate.png", dpi=150)
        plt.close(fig)

    print("\nDone. Output written to:", out_dir)
    print("Key files:")
    print(f"  {out_dir / 'data' / 'agent_ranking.csv'}")
    print(f"  {out_dir / 'data' / 'eval_summary.csv'}")
    print(f"  {out_dir / 'figures' / 'agent_radar.png'}")
    print(f"  {out_dir / 'figures' / 'metrics_heatmap.png'}")


if __name__ == "__main__":
    main()
