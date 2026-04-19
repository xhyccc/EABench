"""
07_paper_figures.py
===================
Generate publication-quality figures for the EABench paper using the
pre-computed CSV data in analyze/output/.

Produces figures for the three evaluated tenants only:
  - Bertrand & Co.  (bertrand-and-co.-20260407)
  - Univ. of Cambford  (staff-office-the-university-of-cambford-20260407)
  - ZAI Intelligence  (zai-intelligence-20260408)

Figures (all PDF):
  1. pass_rate_by_agent_tenant.pdf   – grouped bar: pass rate per agent×tenant
  2. assertion_score_by_agent_tenant.pdf – grouped bar: assertion score
  3. citation_decomposition.pdf      – grouped bar: TS-Rel vs RC-Rel side-by-side
  4. agent_radar.pdf                 – radar/spider chart of aggregate agent metrics
  5. network_comparison.pdf          – grouped bar of network-topology metrics
  6. burstiness_heatmap.pdf          – heatmap: burstiness B by channel×tenant
  7. tool_usage_heatmap.pdf          – heatmap: tool-call frequency by agent×tenant
  8. latency_vs_pass.pdf             – scatter: latency vs pass rate per cell
  9. cost_quality_frontier.pdf       – scatter: prompt tokens vs citation score

Usage:
    python analyze/07_paper_figures.py [--output-dir analyze/output/paper_figures]
"""

import argparse
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

# Three evaluated tenants — full IDs and display labels
TENANT_IDS = [
    "bertrand-and-co.-20260407",
    "staff-office-the-university-of-cambford-20260407",
    "zai-intelligence-20260408",
]
TENANT_LABELS = {
    "bertrand-and-co.-20260407": "Bertrand\n(Law Firm)",
    "staff-office-the-university-of-cambford-20260407": "Cambford\n(University)",
    "zai-intelligence-20260408": "ZAI\n(AI Startup)",
}
TENANT_SHORT = {
    "bertrand-and-co.-20260407": "Bertrand",
    "staff-office-the-university-of-cambford-20260407": "Cambford",
    "zai-intelligence-20260408": "ZAI",
}

AGENT_ORDER = ["react_agent", "react_agent_v2", "react_agent_v3", "researcher_agent"]
AGENT_LABELS = {
    "react_agent": "ReAct-v1",
    "react_agent_v2": "ReAct-v2",
    "react_agent_v3": "ReAct-v3",
    "researcher_agent": "Researcher",
}
AGENT_COLORS = {
    "react_agent": "#4C72B0",
    "react_agent_v2": "#DD8452",
    "react_agent_v3": "#8172B2",
    "researcher_agent": "#55A868",
}
# Non-color visual encodings so agents remain distinguishable in greyscale /
# colourblind settings: bar hatches, line styles, and scatter markers.
AGENT_HATCHES = {
    "react_agent": "",
    "react_agent_v2": "///",
    "react_agent_v3": "xxx",
    "researcher_agent": "...",
}
AGENT_LINESTYLES = {
    "react_agent": "-",
    "react_agent_v2": "--",
    "react_agent_v3": "-.",
    "researcher_agent": ":",
}
AGENT_MARKERS = {
    "react_agent": "o",
    "react_agent_v2": "s",
    "react_agent_v3": "D",
    "researcher_agent": "^",
}

BASE_DIR = Path(__file__).resolve().parent / "output"


def load_eval_summary() -> pd.DataFrame:
    df = pd.read_csv(BASE_DIR / "eval_analysis" / "data" / "eval_summary.csv")
    df = df[df["tenant"].isin(TENANT_IDS)].copy()
    df["agent_label"] = df["agent"].map(AGENT_LABELS)
    df["tenant_label"] = df["tenant"].map(TENANT_LABELS)
    df["tenant_short"] = df["tenant"].map(TENANT_SHORT)
    return df


def load_agent_ranking() -> pd.DataFrame:
    df = pd.read_csv(BASE_DIR / "eval_analysis" / "data" / "agent_ranking.csv")
    df["agent_label"] = df["agent"].map(AGENT_LABELS)
    return df


def load_network_metrics() -> pd.DataFrame:
    df = pd.read_csv(BASE_DIR / "network_analysis" / "data" / "network_metrics.csv")
    df = df[df["tenant"].isin(TENANT_IDS)].copy()
    df["tenant_short"] = df["tenant"].map(TENANT_SHORT)
    return df


def load_iet_summary() -> pd.DataFrame:
    df = pd.read_csv(BASE_DIR / "inter_event_times" / "data" / "iet_summary.csv")
    df = df[df["tenant"].isin(TENANT_IDS)].copy()
    df["tenant_short"] = df["tenant"].map(TENANT_SHORT)
    return df


def load_tool_calls() -> pd.DataFrame:
    df = pd.read_csv(BASE_DIR / "tool_call_analysis" / "data" / "tool_call_frequency.csv")
    # Map short tenant names used in tool_call_frequency.csv to full IDs
    short_to_full = {
        "bertrand": "bertrand-and-co.-20260407",
        "staff": "staff-office-the-university-of-cambford-20260407",
        "zai": "zai-intelligence-20260408",
    }
    df["tenant_full"] = df["tenant"].map(short_to_full)
    df = df.dropna(subset=["tenant_full"]).copy()
    df["agent_label"] = df["agent"].map(AGENT_LABELS)
    df["tenant_short"] = df["tenant_full"].map(TENANT_SHORT)
    return df


# ═══════════════════════════════════════════════════════════════════════
# Figure functions
# ═══════════════════════════════════════════════════════════════════════

def fig_grouped_bar(df, metric, ylabel, title, fname, out):
    """Generic grouped bar: agents grouped by tenant."""
    fig, ax = plt.subplots(figsize=(4.5, 2.8))
    tenants = [TENANT_SHORT[t] for t in TENANT_IDS]
    x = np.arange(len(tenants))
    n = len(AGENT_ORDER)
    w = 0.8 / n
    for i, agent in enumerate(AGENT_ORDER):
        sub = df[df["agent"] == agent].set_index("tenant_short")
        vals = [sub.loc[t, metric] if t in sub.index else 0 for t in tenants]
        bars = ax.bar(x + (i - (n - 1) / 2) * w, vals, w, label=AGENT_LABELS[agent],
                      color=AGENT_COLORS[agent], edgecolor="black", linewidth=0.6,
                      hatch=AGENT_HATCHES[agent])
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                    f"{v:.3f}", ha="center", va="bottom", fontsize=6.5)
    ax.set_xticks(x)
    ax.set_xticklabels(tenants, fontsize=8)
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    ax.set_ylim(0, min(1.0, df[metric].max() * 1.25))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.savefig(out / fname, format="pdf")
    plt.close(fig)
    print(f"  ✓ {fname}")


def fig_citation_decomposition(df, out):
    """Side-by-side TS-Rel vs RC-Rel per agent×tenant."""
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 2.8), sharey=True)
    for ax, metric, title in zip(
        axes,
        ["mean_tool_search_result_relevance", "mean_response_citation_relevance"],
        ["Tool-Search Relevance", "Response-Citation Relevance"],
    ):
        tenants = [TENANT_SHORT[t] for t in TENANT_IDS]
        x = np.arange(len(tenants))
        n = len(AGENT_ORDER)
        w = 0.8 / n
        for i, agent in enumerate(AGENT_ORDER):
            sub = df[df["agent"] == agent].set_index("tenant_short")
            vals = [sub.loc[t, metric] if t in sub.index else 0 for t in tenants]
            bars = ax.bar(x + (i - (n - 1) / 2) * w, vals, w, label=AGENT_LABELS[agent],
                          color=AGENT_COLORS[agent], edgecolor="black", linewidth=0.5,
                          hatch=AGENT_HATCHES[agent])
            for bar, v in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                        f"{v:.2f}", ha="center", va="bottom", fontsize=6)
        ax.set_xticks(x)
        ax.set_xticklabels(tenants, fontsize=7.5)
        ax.set_title(title, fontsize=9)
        ax.set_ylim(0, 1.0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    axes[0].set_ylabel("Relevance Score")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=4, loc="upper center",
               bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout()
    fig.savefig(out / "citation_decomposition.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ citation_decomposition.pdf")


def fig_agent_radar(eval_df, out):
    """Radar chart of per-tenant agent profiles (one subplot per tenant)."""
    metrics = ["pass_rate", "mean_assertion_score",
               "mean_tool_search_result_relevance",
               "mean_response_citation_relevance", "mean_citation_score"]
    mlabels = ["Pass Rate", "Assertion", "TS-Rel", "RC-Rel", "Citation"]
    N = len(metrics)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    fig, axes = plt.subplots(1, 3, figsize=(9, 3.2),
                             subplot_kw=dict(polar=True))
    for ax, tid in zip(axes, TENANT_IDS):
        tenant_data = eval_df[eval_df["tenant"] == tid]
        for _, row in tenant_data.iterrows():
            agent = row["agent"]
            vals = [row[m] for m in metrics]
            vals += vals[:1]
            ax.plot(angles, vals,
                    linestyle=AGENT_LINESTYLES.get(agent, "-"),
                    marker=AGENT_MARKERS.get(agent, "o"),
                    label=AGENT_LABELS.get(agent, agent),
                    color=AGENT_COLORS.get(agent, "#999"), linewidth=1.6, markersize=4)
            ax.fill(angles, vals, alpha=0.06, color=AGENT_COLORS.get(agent, "#999"))
        ax.set_thetagrids(np.degrees(angles[:-1]), mlabels, fontsize=7)
        ax.set_ylim(0, 0.85)
        ax.set_yticklabels([])  # hide radial tick numbers
        ax.set_title(TENANT_SHORT[tid], fontweight="bold", pad=14, fontsize=9)
    # Single shared legend
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=4,
               loc="upper center", bbox_to_anchor=(0.5, -0.02), fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "agent_radar.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ agent_radar.pdf")


def fig_network_comparison(net_df, out):
    """Grouped bar comparing key network metrics across 3 tenants."""
    metrics = [("density", "Density"), ("reciprocity", "Reciprocity"),
               ("transitivity", "Transitivity")]
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.5), sharey=False)
    tenants = net_df["tenant_short"].tolist()
    colors = ["#4C72B0", "#DD8452", "#55A868"]
    for ax, (col, label) in zip(axes, metrics):
        vals = net_df[col].tolist()
        bars = ax.bar(tenants, vals, color=colors, edgecolor="white", width=0.6)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                    f"{v:.3f}", ha="center", va="bottom", fontsize=7)
        ax.set_title(label, fontsize=9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "network_comparison.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ network_comparison.pdf")


def fig_burstiness_heatmap(iet_df, out):
    """Heatmap of burstiness B by channel × tenant."""
    channels = ["email", "chat", "group_chat", "meeting"]
    channel_labels = ["Email", "Chat (1:1)", "Group Chat", "Meeting"]
    tenants = [TENANT_SHORT[t] for t in TENANT_IDS]
    data = []
    for ch in channels:
        row = []
        for tid in TENANT_IDS:
            sub = iet_df[(iet_df["tenant"] == tid) & (iet_df["channel"] == ch)]
            row.append(sub["burstiness"].values[0] if len(sub) > 0 else np.nan)
        data.append(row)
    mat = pd.DataFrame(data, index=channel_labels, columns=tenants)

    fig, ax = plt.subplots(figsize=(3.8, 2.8))
    sns.heatmap(mat, annot=True, fmt=".2f", cmap="RdYlGn_r", center=0,
                linewidths=0.5, ax=ax, vmin=-0.2, vmax=0.7,
                cbar_kws={"label": "Burstiness $B$", "shrink": 0.8})
    fig.tight_layout()
    fig.savefig(out / "burstiness_heatmap.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ burstiness_heatmap.pdf")


def fig_tool_usage_heatmap(tool_df, out):
    """Heatmap: tool-call counts per agent, broken out by tenant (agent × tenant rows)."""
    # Build a pivot with rows = (tenant, agent), columns = tool_name
    tool_df = tool_df.copy()
    tool_df["row_label"] = tool_df["tenant_short"] + " / " + tool_df["agent_label"]
    pivot = tool_df.groupby(["row_label", "tool_name"])["count"].sum().reset_index()
    mat = pivot.pivot(index="row_label", columns="tool_name", values="count").fillna(0)

    # Normalise each row to fractions
    mat = mat.div(mat.sum(axis=1), axis=0)

    # Drop tools with < 1% everywhere
    mat = mat.loc[:, mat.max(axis=0) > 0.01]

    # Order rows: tenant groups, agents within each tenant in canonical order
    ordered_rows = []
    for tid in TENANT_IDS:
        tshort = TENANT_SHORT[tid]
        for agent in AGENT_ORDER:
            label = f"{tshort} / {AGENT_LABELS[agent]}"
            if label in mat.index:
                ordered_rows.append(label)
    mat = mat.loc[ordered_rows]

    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    sns.heatmap(mat, annot=True, fmt=".2f", cmap="YlOrRd", linewidths=0.5, ax=ax,
                cbar_kws={"label": "Fraction of Calls", "shrink": 0.8})
    ax.set_ylabel("")
    # Add horizontal separator lines between tenant groups
    for i in range(1, len(TENANT_IDS)):
        ax.axhline(y=i * len(AGENT_ORDER), color="black", linewidth=1.5)
    fig.tight_layout()
    fig.savefig(out / "tool_usage_heatmap.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ tool_usage_heatmap.pdf")


def fig_latency_vs_pass(df, out):
    """Scatter: mean latency vs pass rate, one point per agent×tenant."""
    fig, ax = plt.subplots(figsize=(4, 3))
    for agent in AGENT_ORDER:
        sub = df[df["agent"] == agent]
        ax.scatter(sub["mean_latency"], sub["pass_rate"],
                   label=AGENT_LABELS[agent], color=AGENT_COLORS[agent],
                   marker=AGENT_MARKERS[agent],
                   s=70, edgecolor="black", linewidth=0.6, zorder=3)
        for _, row in sub.iterrows():
            ax.annotate(row["tenant_short"], (row["mean_latency"], row["pass_rate"]),
                        fontsize=6, textcoords="offset points", xytext=(5, 4))
    ax.set_xlabel("Mean Latency (s)")
    ax.set_ylabel("Pass Rate")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "latency_vs_pass.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ latency_vs_pass.pdf")


def fig_cost_quality_frontier(df, out):
    """Scatter: prompt tokens vs citation score, sized by pass rate."""
    fig, ax = plt.subplots(figsize=(4, 3))
    for agent in AGENT_ORDER:
        sub = df[df["agent"] == agent]
        sizes = sub["pass_rate"] * 300 + 30
        ax.scatter(sub["mean_prompt_tokens"] / 1000, sub["mean_citation_score"],
                   label=AGENT_LABELS[agent], color=AGENT_COLORS[agent],
                   marker=AGENT_MARKERS[agent],
                   s=sizes, alpha=0.75, edgecolor="black", linewidth=0.6, zorder=3)
        for _, row in sub.iterrows():
            ax.annotate(row["tenant_short"],
                        (row["mean_prompt_tokens"] / 1000, row["mean_citation_score"]),
                        fontsize=6, textcoords="offset points", xytext=(5, 4))
    ax.set_xlabel("Mean Prompt Tokens (×1k)")
    ax.set_ylabel("Citation Score")
    ax.legend(frameon=False, title="Agent (size ∝ pass rate)", title_fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "cost_quality_frontier.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ cost_quality_frontier.pdf")


def fig_metrics_heatmap(df, out):
    """Heatmap of key metrics: rows = agent×tenant, cols = metrics."""
    metrics = ["pass_rate", "mean_assertion_score",
               "mean_tool_search_result_relevance",
               "mean_response_citation_relevance",
               "mean_citation_score"]
    labels = ["Pass Rate", "Assertion", "TS-Rel", "RC-Rel", "Citation"]
    rows = []
    row_labels = []
    for tid in TENANT_IDS:
        for agent in AGENT_ORDER:
            sub = df[(df["tenant"] == tid) & (df["agent"] == agent)]
            if len(sub) == 0:
                continue
            row = sub.iloc[0]
            rows.append([row[m] for m in metrics])
            row_labels.append(f"{TENANT_SHORT[tid]} / {AGENT_LABELS[agent]}")
    mat = pd.DataFrame(rows, index=row_labels, columns=labels)

    fig, ax = plt.subplots(figsize=(5, 4))
    sns.heatmap(mat, annot=True, fmt=".3f", cmap="YlGnBu", linewidths=0.5, ax=ax,
                cbar_kws={"label": "Score", "shrink": 0.7})
    fig.tight_layout()
    fig.savefig(out / "metrics_heatmap.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ metrics_heatmap.pdf")


# ═══════════════════════════════════════════════════════════════════════
# Query-type breakdown helpers
# ═══════════════════════════════════════════════════════════════════════

import json
import re
import yaml

# Map result files to (tenant_id, agent_id)
RESULT_DIR = Path(__file__).resolve().parent.parent / "python" / "results"
TENANT_DIRS = {
    "bertrand-and-co.-20260407": Path(__file__).resolve().parent.parent / "examples" / "tenants" / "bertrand-and-co.-20260407",
    "staff-office-the-university-of-cambford-20260407": Path(__file__).resolve().parent.parent / "examples" / "tenants" / "staff-office-the-university-of-cambford-20260407",
    "zai-intelligence-20260408": Path(__file__).resolve().parent.parent / "examples" / "tenants" / "zai-intelligence-20260408",
}

QUERY_TYPE_LABELS = {"search": "Targeted Artifact Search", "multihop": "Multi-Hop Reasoning", "report": "Comprehensive Report"}
QUERY_TYPE_ORDER = ["search", "multihop", "report"]
QUERY_TYPE_COLORS = {"search": "#4C72B0", "multihop": "#DD8452", "report": "#55A868"}

_REPORT_RE = re.compile(
    r"^(provide|generate|create|compile|draft|prepare|produce|summarize|write)\b", re.I
)


def _classify_eval_cases(eval_yaml_path: str) -> dict:
    """Return {case_id: query_type} for an eval YAML."""
    with open(eval_yaml_path) as f:
        data = yaml.safe_load(f)
    mapping = {}
    for c in data["cases"]:
        el = c.get("entity_list", [])
        q = c["query"].strip()
        if len(el) <= 1:
            qtype = "search"
        elif _REPORT_RE.match(q):
            qtype = "report"
        else:
            qtype = "multihop"
        mapping[c["id"]] = qtype
    return mapping


def load_query_type_metrics() -> pd.DataFrame:
    """Load per-case metrics from result JSONs with query-type labels.

    Returns a DataFrame with columns:
      tenant, agent, case_id, query_type, assertion_score,
      citation_score, tool_citation_score, response_citation_score,
      tool_search_result_relevance, response_citation_relevance
    """
    rows = []
    _type_cache: dict[str, dict] = {}  # eval_yaml_path -> case classification

    for fname in sorted(os.listdir(RESULT_DIR)):
        if not fname.endswith(".json"):
            continue
        if "glmjudge" in fname or "baseline" in fname:
            continue
        with open(RESULT_DIR / fname) as fh:
            data = json.load(fh)
        if "metadata" not in data or "agent_config" not in data.get("metadata", {}):
            continue  # skip judge-only or malformed files
        meta = data["metadata"]
        tenant_path = meta["tenant"]
        tenant_id = os.path.basename(os.path.dirname(tenant_path))
        if tenant_id not in TENANT_IDS:
            continue
        agent = os.path.basename(meta["agent_config"]).replace(".yaml", "")
        if agent not in AGENT_ORDER:
            continue

        # Resolve eval YAML relative to project root
        eval_rel = meta["eval_set"]
        eval_abs = str((RESULT_DIR / ".." / eval_rel).resolve())
        if eval_abs not in _type_cache:
            _type_cache[eval_abs] = _classify_eval_cases(eval_abs)
        type_map = _type_cache[eval_abs]

        for case in data["cases"]:
            cid = case["case_id"]
            m = case["metrics"]
            rows.append({
                "tenant": tenant_id,
                "agent": agent,
                "case_id": cid,
                "query_type": type_map.get(cid, "unknown"),
                "assertion_score": m.get("assertion_score", 0),
                "citation_score": m.get("citation_score", 0),
                "tool_citation_score": m.get("tool_citation_score", 0),
                "response_citation_score": m.get("response_citation_score", 0),
                "tool_search_result_relevance": m.get("tool_search_result_relevance", 0),
                "response_citation_relevance": m.get("response_citation_relevance", 0),
            })

    df = pd.DataFrame(rows)
    df["agent_label"] = df["agent"].map(AGENT_LABELS)
    df["tenant_short"] = df["tenant"].map(TENANT_SHORT)
    df["qtype_label"] = df["query_type"].map(QUERY_TYPE_LABELS)
    return df


# ── Bar chart: assertion score by query type ──────────────────────────

def fig_assertion_by_query_type(qt_df: pd.DataFrame, out: Path):
    """Grouped bar: mean assertion score by query type, faceted by tenant."""
    fig, axes = plt.subplots(1, 3, figsize=(10, 2.8), sharey=True)
    for ax, tid in zip(axes, TENANT_IDS):
        sub = qt_df[qt_df["tenant"] == tid]
        agg = sub.groupby(["query_type", "agent"])["assertion_score"].mean().reset_index()
        x = np.arange(len(QUERY_TYPE_ORDER))
        n = len(AGENT_ORDER)
        w = 0.8 / n
        for i, agent in enumerate(AGENT_ORDER):
            a_sub = agg[agg["agent"] == agent]
            vals = []
            for qt in QUERY_TYPE_ORDER:
                row = a_sub[a_sub["query_type"] == qt]
                vals.append(row["assertion_score"].values[0] if len(row) else 0)
            bars = ax.bar(x + (i - (n - 1) / 2) * w, vals, w,
                          label=AGENT_LABELS[agent], color=AGENT_COLORS[agent],
                          edgecolor="black", linewidth=0.5,
                          hatch=AGENT_HATCHES[agent])
            for bar, v in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                        f"{v:.2f}", ha="center", va="bottom", fontsize=5.5)
        ax.set_xticks(x)
        ax.set_xticklabels([QUERY_TYPE_LABELS[q] for q in QUERY_TYPE_ORDER], fontsize=5.5, rotation=12, ha="right")
        ax.set_xlabel(TENANT_SHORT[tid], fontsize=9)
        ax.set_ylim(0, 1.15)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    axes[0].set_ylabel("Assertion Score")
    axes[1].legend(frameon=False, ncol=4, loc="upper center",
                   bbox_to_anchor=(0.5, -0.18), fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "assertion_by_query_type.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ assertion_by_query_type.pdf")


# ── Bar chart: citation score by query type ───────────────────────────

def fig_citation_by_query_type(qt_df: pd.DataFrame, out: Path):
    """Grouped bar: mean citation score by query type, faceted by tenant."""
    fig, axes = plt.subplots(1, 3, figsize=(10, 2.8), sharey=True)
    for ax, tid in zip(axes, TENANT_IDS):
        sub = qt_df[qt_df["tenant"] == tid]
        agg = sub.groupby(["query_type", "agent"])["citation_score"].mean().reset_index()
        x = np.arange(len(QUERY_TYPE_ORDER))
        n = len(AGENT_ORDER)
        w = 0.8 / n
        for i, agent in enumerate(AGENT_ORDER):
            a_sub = agg[agg["agent"] == agent]
            vals = []
            for qt in QUERY_TYPE_ORDER:
                row = a_sub[a_sub["query_type"] == qt]
                vals.append(row["citation_score"].values[0] if len(row) else 0)
            bars = ax.bar(x + (i - (n - 1) / 2) * w, vals, w,
                          label=AGENT_LABELS[agent], color=AGENT_COLORS[agent],
                          edgecolor="black", linewidth=0.5,
                          hatch=AGENT_HATCHES[agent])
            for bar, v in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                        f"{v:.2f}", ha="center", va="bottom", fontsize=5.5)
        ax.set_xticks(x)
        ax.set_xticklabels([QUERY_TYPE_LABELS[q] for q in QUERY_TYPE_ORDER], fontsize=5.5, rotation=12, ha="right")
        ax.set_xlabel(TENANT_SHORT[tid], fontsize=9)
        ax.set_ylim(0, 1.15)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    axes[0].set_ylabel("Citation Score")
    axes[1].legend(frameon=False, ncol=4, loc="upper center",
                   bbox_to_anchor=(0.5, -0.18), fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "citation_by_query_type.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ citation_by_query_type.pdf")


# ── Bar chart: citation decomposition by query type ───────────────────

def fig_citation_decomp_by_query_type(qt_df: pd.DataFrame, out: Path):
    """2×3 grid: TS-Rel and RC-Rel by query type, one column per tenant."""
    metrics = [
        ("tool_search_result_relevance", "Tool-Search Relevance"),
        ("response_citation_relevance", "Response-Citation Relevance"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(10, 5), sharey=True)
    for row, (metric, label) in enumerate(metrics):
        for col, tid in enumerate(TENANT_IDS):
            ax = axes[row, col]
            sub = qt_df[qt_df["tenant"] == tid]
            agg = sub.groupby(["query_type", "agent"])[metric].mean().reset_index()
            x = np.arange(len(QUERY_TYPE_ORDER))
            n = len(AGENT_ORDER)
            w = 0.8 / n
            for i, agent in enumerate(AGENT_ORDER):
                a_sub = agg[agg["agent"] == agent]
                vals = []
                for qt in QUERY_TYPE_ORDER:
                    r = a_sub[a_sub["query_type"] == qt]
                    vals.append(r[metric].values[0] if len(r) else 0)
                bars = ax.bar(x + (i - (n - 1) / 2) * w, vals, w,
                              label=AGENT_LABELS[agent], color=AGENT_COLORS[agent],
                              edgecolor="black", linewidth=0.5,
                              hatch=AGENT_HATCHES[agent])
                for bar, v in zip(bars, vals):
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                            f"{v:.2f}", ha="center", va="bottom", fontsize=5)
            ax.set_xticks(x)
            ax.set_xticklabels([QUERY_TYPE_LABELS[q] for q in QUERY_TYPE_ORDER], fontsize=5, rotation=12, ha="right")
            ax.set_ylim(0, 1.15)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            if row == 0:
                ax.set_xlabel(TENANT_SHORT[tid], fontsize=9)
                ax.xaxis.set_label_position("top")
            if col == 0:
                ax.set_ylabel(label, fontsize=8)
    # Single legend at bottom
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=4,
               loc="lower center", bbox_to_anchor=(0.5, -0.02), fontsize=7)
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(out / "citation_decomp_by_query_type.pdf", format="pdf")
    plt.close(fig)
    print("  ✓ citation_decomp_by_query_type.pdf")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Generate paper figures (3 tenants)")
    parser.add_argument("--output-dir", default="analyze/output/paper_figures",
                        help="Output directory for PDF figures")
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("Loading data …")
    eval_df = load_eval_summary()
    ranking_df = load_agent_ranking()
    net_df = load_network_metrics()
    iet_df = load_iet_summary()
    tool_df = load_tool_calls()

    print(f"\nGenerating figures → {out}/")

    # 1-2. Grouped bars for pass rate and assertion score
    fig_grouped_bar(eval_df, "pass_rate", "Pass Rate",
                    "Pass Rate by Agent and Tenant", "pass_rate_by_agent_tenant.pdf", out)
    fig_grouped_bar(eval_df, "mean_assertion_score", "Assertion Score",
                    "Assertion Score by Agent and Tenant",
                    "assertion_score_by_agent_tenant.pdf", out)

    # 3. Citation decomposition
    fig_citation_decomposition(eval_df, out)

    # 4. Agent radar (per-tenant)
    fig_agent_radar(eval_df, out)

    # 5. Network comparison
    fig_network_comparison(net_df, out)

    # 6. Burstiness heatmap
    fig_burstiness_heatmap(iet_df, out)

    # 7. Tool usage heatmap
    fig_tool_usage_heatmap(tool_df, out)

    # 8. Latency vs pass rate
    fig_latency_vs_pass(eval_df, out)

    # 9. Cost–quality frontier
    fig_cost_quality_frontier(eval_df, out)

    # 10. Metrics heatmap
    fig_metrics_heatmap(eval_df, out)

    # 11-13. Query-type breakdown figures
    print("\nLoading query-type metrics from result JSONs …")
    qt_df = load_query_type_metrics()
    fig_assertion_by_query_type(qt_df, out)
    fig_citation_by_query_type(qt_df, out)
    fig_citation_decomp_by_query_type(qt_df, out)

    print(f"\nDone — {len(list(out.glob('*.pdf')))} PDF figures in {out}/")


if __name__ == "__main__":
    main()
