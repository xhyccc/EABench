"""
06_tool_call_analysis.py
========================
Tool-call analysis for EABench evaluation results.

Analyses all result files in python/results/ to answer:
  A. Which tools are called most often, and how does that vary across tenants
     and agents?
  B. How reliable are tool responses (error rate, result count)?
  C. Are more tool calls or more results correlated with better assertion scores?
  D. Which tools commonly appear together within the same evaluation case?

Produces:
  A. Tool call frequency
     1. Bar chart: total call counts per tool (sorted)
     2. Grouped bar: per-tenant, normalized
     3. Grouped bar: per-agent, normalized
     4. Heatmap: tool × tenant (call counts)

  B. Tool response analysis
     5. Stacked bar: error / no_results / has_results proportion per tool
     6. Box/violin: number of results returned per tool (search tools only)
     7. Scatter: result count vs assertion_score
     8. Heatmap: mean result count per (tool × tenant)

  C. Tool call patterns
     9. Histogram: tool_calls_count per case, coloured by agent
    10. Co-occurrence heatmap: tools appearing in same case
    11. Bar: mean tool_calls_count per (tenant × agent)

  D. Error analysis
    12. Bar: error rate per tool type

Usage
-----
    python analyze/06_tool_call_analysis.py \\
        --results-dir python/results \\
        --output-dir  analyze/output/tool_call_analysis
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

TOOL_COLORS = {
    "search_email":      "#4C72B0",
    "search_file":       "#DD8452",
    "search_meeting":    "#55A868",
    "search_chat":       "#C44E52",
    "search_group_chat": "#8172B2",
    "search_people":     "#937860",
    "read_file":         "#DA8BC3",
    "search_in_file":    "#8C8C8C",
    "execute_python":    "#CCB974",
    "search_channel":    "#64B5CD",
}

SEARCH_TOOLS = {
    "search_email", "search_file", "search_meeting",
    "search_chat", "search_group_chat", "search_people",
    "search_in_file", "search_channel",
}

RESULT_COLORS = {
    "has_results": "#55A868",
    "no_results":  "#937860",
    "error":       "#C44E52",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def short_tenant(path: str) -> str:
    """Extract a short tenant label from a full path string."""
    p = Path(path)
    for part in p.parts:
        if "tenants" in p.parts:
            idx = list(p.parts).index("tenants")
            if len(p.parts) > idx + 1:
                name = p.parts[idx + 1]
                s = name.split("-")[0]
                return s if len(s) >= 3 else name[:14]
    # Fallback: try to get tenant from filename
    name = p.stem
    return name[:14]


def extract_tenant(metadata: dict) -> str:
    tenant_path = metadata.get("tenant", metadata.get("tenant_path", ""))
    return short_tenant(tenant_path)


def extract_agent(metadata: dict) -> str:
    agent_path = metadata.get("agent_config", "")
    return Path(agent_path).stem


def classify_result(result_str: str) -> str:
    """Classify a tool call result string."""
    if not result_str:
        return "no_results"
    r = str(result_str)
    if "Error" in r or "error" in r[:50]:
        return "error"
    if "'score':" in r or "score" in r:
        return "has_results"
    if r.strip() in ("", "[]", "None", "null"):
        return "no_results"
    return "has_results"


def count_results(result_str: str) -> int:
    """Count number of results returned (number of 'score' occurrences)."""
    if not result_str:
        return 0
    return len(re.findall(r"'score'\s*:", str(result_str)))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_results(results_dir: Path) -> list[dict]:
    """
    Load all eval JSON files. Returns a flat list of case records augmented
    with 'tenant', 'agent', 'filename' fields.
    """
    records = []
    for path in sorted(results_dir.glob("eval_*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  Warning: could not read {path}: {exc}", file=sys.stderr)
            continue

        meta = data.get("metadata", {})
        tenant = extract_tenant(meta)
        agent = extract_agent(meta)

        for case in data.get("cases", []):
            records.append({
                "case_id":         case.get("case_id"),
                "tenant":          tenant,
                "agent":           agent,
                "filename":        path.name,
                "query":           case.get("query", ""),
                "tool_calls":      case.get("tool_calls", []),
                "metrics":         case.get("metrics", {}),
                "passed":          case.get("passed", False),
                "assertion_score": (case.get("metrics") or {}).get("assertion_score", None),
                "tool_calls_count":(case.get("metrics") or {}).get("tool_calls_count",
                                    len(case.get("tool_calls", []))),
            })
    return records


def build_tool_call_rows(cases: list[dict]) -> pd.DataFrame:
    """Explode cases into one row per tool call."""
    rows = []
    for case in cases:
        for tc in case["tool_calls"]:
            result_str = str(tc.get("result", "") or "")
            classification = classify_result(result_str)
            n_results = count_results(result_str)
            rows.append({
                "tenant":          case["tenant"],
                "agent":           case["agent"],
                "case_id":         case["case_id"],
                "tool_name":       tc.get("name", "unknown"),
                "result_class":    classification,
                "n_results":       n_results,
                "assertion_score": case["assertion_score"],
                "passed":          case["passed"],
                "tool_calls_count":case["tool_calls_count"],
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["tenant", "agent", "case_id", "tool_name", "result_class",
                 "n_results", "assertion_score", "passed", "tool_calls_count"]
    )


# ---------------------------------------------------------------------------
# A. Tool call frequency
# ---------------------------------------------------------------------------

def plot_tool_frequency_bar(tc_df: pd.DataFrame, save_path: Path) -> None:
    counts = tc_df["tool_name"].value_counts()
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = [TOOL_COLORS.get(t, "#aaaaaa") for t in counts.index]
    counts.plot.bar(ax=ax, color=colors)
    ax.set_title("Total Tool Call Counts", fontsize=13)
    ax.set_xlabel("Tool")
    ax.set_ylabel("Count")
    ax.tick_params(axis="x", rotation=35)
    for rect in ax.patches:
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 0.3,
                str(int(rect.get_height())), ha="center", va="bottom", fontsize=8)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_tool_by_tenant_normalized(tc_df: pd.DataFrame, save_path: Path) -> None:
    if tc_df.empty:
        return
    pivot = tc_df.groupby(["tenant", "tool_name"]).size().unstack(fill_value=0)
    # Normalize each tenant row to fraction
    pivot_norm = pivot.div(pivot.sum(axis=1), axis=0)
    tools = pivot_norm.columns.tolist()
    tenants = pivot_norm.index.tolist()
    x = np.arange(len(tools))
    w = 0.8 / max(len(tenants), 1)
    palette = sns.color_palette("tab10", len(tenants))

    fig, ax = plt.subplots(figsize=(12, 5))
    for i, tenant in enumerate(tenants):
        vals = [pivot_norm.loc[tenant, t] if t in pivot_norm.columns else 0 for t in tools]
        ax.bar(x + i * w, vals, w, label=tenant, color=palette[i], alpha=0.85)
    ax.set_xticks(x + w * (len(tenants) - 1) / 2)
    ax.set_xticklabels(tools, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("Fraction of calls per tenant")
    ax.set_title("Tool Call Distribution per Tenant (Normalized)", fontsize=13)
    ax.legend(fontsize=8, bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_tool_by_agent_normalized(tc_df: pd.DataFrame, save_path: Path) -> None:
    if tc_df.empty:
        return
    pivot = tc_df.groupby(["agent", "tool_name"]).size().unstack(fill_value=0)
    pivot_norm = pivot.div(pivot.sum(axis=1), axis=0)
    tools = pivot_norm.columns.tolist()
    agents = pivot_norm.index.tolist()
    x = np.arange(len(tools))
    w = 0.8 / max(len(agents), 1)
    palette = sns.color_palette("Set2", len(agents))

    fig, ax = plt.subplots(figsize=(12, 5))
    for i, agent in enumerate(agents):
        vals = [pivot_norm.loc[agent, t] if t in pivot_norm.columns else 0 for t in tools]
        ax.bar(x + i * w, vals, w, label=agent, color=palette[i], alpha=0.85)
    ax.set_xticks(x + w * (len(agents) - 1) / 2)
    ax.set_xticklabels(tools, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("Fraction of calls per agent")
    ax.set_title("Tool Call Distribution per Agent (Normalized)", fontsize=13)
    ax.legend(fontsize=8, bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_tool_tenant_heatmap(tc_df: pd.DataFrame, save_path: Path) -> None:
    if tc_df.empty:
        return
    pivot = tc_df.groupby(["tool_name", "tenant"]).size().unstack(fill_value=0)
    fig, ax = plt.subplots(figsize=(max(8, len(pivot.columns) * 1.5),
                                    max(5, len(pivot) * 0.6)))
    sns.heatmap(pivot, annot=True, fmt="d", cmap="Blues", linewidths=0.4,
                ax=ax, cbar_kws={"label": "Call count"})
    ax.set_title("Tool Call Count Heatmap (tool × tenant)", fontsize=13)
    ax.set_xlabel("Tenant")
    ax.set_ylabel("Tool")
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


# ---------------------------------------------------------------------------
# B. Tool response analysis
# ---------------------------------------------------------------------------

def plot_result_class_stacked_bar(tc_df: pd.DataFrame, save_path: Path) -> None:
    if tc_df.empty:
        return
    pivot = tc_df.groupby(["tool_name", "result_class"]).size().unstack(fill_value=0)
    for cls in ["has_results", "no_results", "error"]:
        if cls not in pivot.columns:
            pivot[cls] = 0
    pivot_norm = pivot.div(pivot.sum(axis=1), axis=0)

    tools = pivot_norm.index.tolist()
    x = np.arange(len(tools))
    fig, ax = plt.subplots(figsize=(10, 5))
    bottom = np.zeros(len(tools))
    for cls in ["has_results", "no_results", "error"]:
        vals = pivot_norm[cls].values
        ax.bar(x, vals, bottom=bottom, label=cls, color=RESULT_COLORS[cls])
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels(tools, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("Proportion")
    ax.set_title("Tool Response Classification per Tool", fontsize=13)
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_result_count_violin(tc_df: pd.DataFrame, save_path: Path) -> None:
    search_df = tc_df[tc_df["tool_name"].isin(SEARCH_TOOLS) & (tc_df["n_results"] > 0)].copy()
    if search_df.empty:
        return
    tools_with_data = search_df["tool_name"].value_counts()
    tools_with_data = tools_with_data[tools_with_data >= 3].index.tolist()
    search_df = search_df[search_df["tool_name"].isin(tools_with_data)]
    if search_df.empty:
        return

    fig, ax = plt.subplots(figsize=(11, 5))
    sns.violinplot(data=search_df, x="tool_name", y="n_results",
                   hue="tool_name", legend=False,
                   palette={t: TOOL_COLORS.get(t, "#aaaaaa") for t in tools_with_data},
                   inner="box", ax=ax, order=tools_with_data)
    ax.set_title("Result Count Distribution per Search Tool", fontsize=13)
    ax.set_xlabel("Tool")
    ax.set_ylabel("Number of results returned")
    ax.tick_params(axis="x", rotation=35)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_results_vs_assertion_scatter(tc_df: pd.DataFrame, save_path: Path) -> None:
    df = tc_df.dropna(subset=["assertion_score"])
    if df.empty:
        return
    case_level = (
        df.groupby(["case_id", "tenant", "agent"])
        .agg(total_results=("n_results", "sum"), assertion_score=("assertion_score", "first"))
        .reset_index()
    )
    if case_level.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    palette = sns.color_palette("tab10", len(case_level["tenant"].unique()))
    for i, (tenant, grp) in enumerate(case_level.groupby("tenant")):
        ax.scatter(grp["total_results"], grp["assertion_score"],
                   s=20, alpha=0.5, label=tenant, color=palette[i])

    # Add regression line
    x = case_level["total_results"].values
    y = case_level["assertion_score"].values
    if len(x) > 2 and x.std() > 0:
        coeffs = np.polyfit(x, y, 1)
        xfit = np.linspace(x.min(), x.max(), 100)
        ax.plot(xfit, np.polyval(coeffs, xfit), "--", color="black",
                linewidth=1.5, label=f"OLS slope={coeffs[0]:.3f}")

    ax.set_xlabel("Total results returned per case")
    ax.set_ylabel("Assertion score")
    ax.set_title("Results Returned vs Assertion Score", fontsize=13)
    ax.legend(fontsize=8, bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_mean_result_count_heatmap(tc_df: pd.DataFrame, save_path: Path) -> None:
    if tc_df.empty:
        return
    pivot = tc_df.groupby(["tool_name", "tenant"])["n_results"].mean().unstack(fill_value=0)
    fig, ax = plt.subplots(figsize=(max(8, len(pivot.columns) * 1.5),
                                    max(5, len(pivot) * 0.6)))
    sns.heatmap(pivot.round(1), annot=True, fmt=".1f", cmap="YlOrRd",
                linewidths=0.4, ax=ax, cbar_kws={"label": "Mean result count"})
    ax.set_title("Mean Result Count per (Tool × Tenant)", fontsize=13)
    ax.set_xlabel("Tenant")
    ax.set_ylabel("Tool")
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


# ---------------------------------------------------------------------------
# C. Tool call patterns
# ---------------------------------------------------------------------------

def plot_tool_calls_histogram(cases: list[dict], save_path: Path) -> None:
    df = pd.DataFrame([
        {"tool_calls_count": c["tool_calls_count"], "agent": c["agent"]}
        for c in cases if c["tool_calls_count"] is not None
    ])
    if df.empty:
        return
    agents = df["agent"].unique().tolist()
    palette = sns.color_palette("Set2", len(agents))

    fig, ax = plt.subplots(figsize=(9, 5))
    max_tc = int(df["tool_calls_count"].max())
    bins = np.arange(0, max_tc + 2, 1)
    for i, agent in enumerate(agents):
        sub = df[df["agent"] == agent]["tool_calls_count"]
        ax.hist(sub, bins=bins, alpha=0.6, label=agent, color=palette[i])
    ax.set_title("Distribution of Tool Calls per Case", fontsize=13)
    ax.set_xlabel("Number of tool calls per case")
    ax.set_ylabel("Case count")
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_tool_cooccurrence(cases: list[dict], save_path: Path) -> None:
    """Co-occurrence heatmap: tools appearing in the same case."""
    all_tools = sorted(TOOL_COLORS.keys())
    cooccur = pd.DataFrame(0, index=all_tools, columns=all_tools, dtype=int)

    for case in cases:
        tools_in_case = set(tc.get("name", "") for tc in case["tool_calls"])
        tools_in_case = tools_in_case.intersection(all_tools)
        for t1, t2 in combinations(sorted(tools_in_case), 2):
            cooccur.loc[t1, t2] += 1
            cooccur.loc[t2, t1] += 1
        for t in tools_in_case:
            cooccur.loc[t, t] += 1

    # Drop zero rows/cols
    nonzero = cooccur.sum(axis=1) > 0
    cooccur = cooccur.loc[nonzero, nonzero]
    if cooccur.empty:
        return

    fig, ax = plt.subplots(figsize=(max(7, len(cooccur) * 0.9),
                                    max(6, len(cooccur) * 0.9)))
    mask = np.zeros_like(cooccur, dtype=bool)
    np.fill_diagonal(mask, True)
    sns.heatmap(cooccur, mask=mask, annot=True, fmt="d", cmap="Blues",
                linewidths=0.3, ax=ax, cbar_kws={"label": "Co-occurrence count"})
    sns.heatmap(cooccur, mask=~mask, annot=True, fmt="d", cmap="Greys",
                linewidths=0.3, ax=ax, cbar=False)
    ax.set_title("Tool Co-occurrence in Same Case", fontsize=13)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_mean_tool_calls_per_tenant_agent(cases: list[dict], save_path: Path) -> None:
    df = pd.DataFrame([
        {"tenant": c["tenant"], "agent": c["agent"], "tool_calls_count": c["tool_calls_count"]}
        for c in cases if c["tool_calls_count"] is not None
    ])
    if df.empty:
        return
    agg = df.groupby(["tenant", "agent"])["tool_calls_count"].mean().reset_index()
    pivot = agg.pivot_table(index="tenant", columns="agent", values="tool_calls_count", fill_value=0)
    agents = pivot.columns.tolist()
    tenants = pivot.index.tolist()
    x = np.arange(len(tenants))
    w = 0.8 / max(len(agents), 1)
    palette = sns.color_palette("Set2", len(agents))

    fig, ax = plt.subplots(figsize=(10, 5))
    for i, agent in enumerate(agents):
        vals = [pivot.loc[t, agent] if agent in pivot.columns else 0 for t in tenants]
        ax.bar(x + i * w, vals, w, label=agent, color=palette[i], alpha=0.85)
    ax.set_xticks(x + w * (len(agents) - 1) / 2)
    ax.set_xticklabels(tenants, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Mean tool calls per case")
    ax.set_title("Mean Tool Calls per Case (Tenant × Agent)", fontsize=13)
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


# ---------------------------------------------------------------------------
# D. Error analysis
# ---------------------------------------------------------------------------

def plot_error_rate(tc_df: pd.DataFrame, save_path: Path) -> None:
    if tc_df.empty:
        return
    pivot = tc_df.groupby(["tool_name", "result_class"]).size().unstack(fill_value=0)
    for cls in ["has_results", "no_results", "error"]:
        if cls not in pivot.columns:
            pivot[cls] = 0
    totals = pivot.sum(axis=1)
    error_rate = (pivot["error"] / totals.replace(0, np.nan)).fillna(0)
    error_rate = error_rate.sort_values(ascending=False)

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = [TOOL_COLORS.get(t, "#aaaaaa") for t in error_rate.index]
    ax.bar(error_rate.index, error_rate.values * 100, color=colors)
    ax.set_title("Error Rate per Tool Type", fontsize=13)
    ax.set_xlabel("Tool")
    ax.set_ylabel("Error rate (%)")
    ax.set_ylim(0, max(error_rate.max() * 110, 5))
    for rect, val in zip(ax.patches, error_rate.values):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 0.5,
                f"{val * 100:.1f}%", ha="center", va="bottom", fontsize=8)
    ax.tick_params(axis="x", rotation=35)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def summarise_common_errors(tc_df: pd.DataFrame, save_path: Path) -> None:
    """Save a CSV of common error snippets per tool."""
    if tc_df.empty:
        return
    # (We can't store raw results in tc_df, so this is a placeholder that
    # counts error occurrences from result_class.)
    err_df = tc_df[tc_df["result_class"] == "error"]
    if err_df.empty:
        return
    err_counts = err_df.groupby("tool_name").size().reset_index(name="error_count")
    err_counts["error_rate"] = (
        err_counts["error_count"]
        / tc_df.groupby("tool_name").size().loc[err_counts["tool_name"]].values
    )
    err_counts.to_csv(save_path, index=False)
    print(f"  Saved: {save_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Tool call analysis for EABench")
    parser.add_argument(
        "--results-dir",
        default=str(REPO_ROOT / "python" / "results"),
        help="Directory containing eval_*.json result files",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "analyze" / "output" / "tool_call_analysis"),
        help="Root output directory",
    )
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir)
    fig_dir = output_dir / "figures"
    data_dir = output_dir / "data"
    fig_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    print("Loading result files …")
    cases = load_all_results(results_dir)
    if not cases:
        print("No eval result files found. Exiting.", file=sys.stderr)
        sys.exit(1)
    print(f"  Loaded {len(cases)} cases from {results_dir}")

    tc_df = build_tool_call_rows(cases)
    print(f"  Total tool calls: {len(tc_df)}")

    # Save raw tool call table
    tc_df.to_csv(data_dir / "tool_calls.csv", index=False)
    print(f"  Saved: {data_dir / 'tool_calls.csv'}")

    # ------------------------------------------------------------------
    # A. Tool call frequency
    # ------------------------------------------------------------------
    print("\n=== A. Tool call frequency ===")
    plot_tool_frequency_bar(tc_df, fig_dir / "01_tool_frequency.pdf")
    plot_tool_by_tenant_normalized(tc_df, fig_dir / "02_tool_by_tenant_normalized.pdf")
    plot_tool_by_agent_normalized(tc_df, fig_dir / "03_tool_by_agent_normalized.pdf")
    plot_tool_tenant_heatmap(tc_df, fig_dir / "04_tool_tenant_heatmap.pdf")

    # ------------------------------------------------------------------
    # B. Tool response analysis
    # ------------------------------------------------------------------
    print("\n=== B. Tool response analysis ===")
    plot_result_class_stacked_bar(tc_df, fig_dir / "05_result_class_stacked.pdf")
    plot_result_count_violin(tc_df, fig_dir / "06_result_count_violin.pdf")
    plot_results_vs_assertion_scatter(tc_df, fig_dir / "07_results_vs_assertion.pdf")
    plot_mean_result_count_heatmap(tc_df, fig_dir / "08_mean_result_count_heatmap.pdf")

    # ------------------------------------------------------------------
    # C. Tool call patterns
    # ------------------------------------------------------------------
    print("\n=== C. Tool call patterns ===")
    plot_tool_calls_histogram(cases, fig_dir / "09_tool_calls_histogram.pdf")
    plot_tool_cooccurrence(cases, fig_dir / "10_tool_cooccurrence.pdf")
    plot_mean_tool_calls_per_tenant_agent(cases, fig_dir / "11_mean_tool_calls_bar.pdf")

    # ------------------------------------------------------------------
    # D. Error analysis
    # ------------------------------------------------------------------
    print("\n=== D. Error analysis ===")
    plot_error_rate(tc_df, fig_dir / "12_error_rate.pdf")
    summarise_common_errors(tc_df, data_dir / "error_summary.csv")

    # ------------------------------------------------------------------
    # Summary tables
    # ------------------------------------------------------------------
    freq_table = tc_df.groupby(["tool_name", "tenant", "agent"]).size().reset_index(name="count")
    freq_table.to_csv(data_dir / "tool_call_frequency.csv", index=False)
    print(f"  Saved: {data_dir / 'tool_call_frequency.csv'}")

    class_table = (
        tc_df.groupby(["tool_name", "result_class"]).size()
        .unstack(fill_value=0)
        .reset_index()
    )
    class_table.to_csv(data_dir / "result_classification.csv", index=False)
    print(f"  Saved: {data_dir / 'result_classification.csv'}")

    print("\nDone. All figures in:", fig_dir)
    print("All data in:", data_dir)


if __name__ == "__main__":
    main()
