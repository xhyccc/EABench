"""
05_data_distribution.py
=======================
Data distribution analysis for EABench tenant corpora.

Produces rich visualisations covering:
  A. Entity counts per type per tenant
     - Stacked bar charts (generation_log entities, eval test cases)
     - Heatmap: entity_type × tenant
     - Pie charts per tenant
  B. Inter-event time summary (cross-tenant comparison)
     - Box plots of IET distributions per channel type
     - Mean IET per channel per tenant (heatmap and grouped bar)
  C. Scale-free / power-law properties per communication channel
     - Log-log CCDF per tenant (4-panel per tenant figure)
     - Cross-tenant gamma exponents per channel (grouped bar)
  D. File author distribution (Zipf's law)
     - Log-rank vs log-count scatter per tenant
  E. Cross-tenant summary table (CSV)

Usage
-----
    python analyze/05_data_distribution.py \\
        --tenants-dir examples/tenants \\
        --output-dir  analyze/output/data_distribution
"""

import argparse
import json
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
import yaml

# ---------------------------------------------------------------------------
# Colour palette (consistent with existing scripts)
# ---------------------------------------------------------------------------

CHANNEL_COLORS = {
    "email":      "#4C72B0",
    "chat":       "#DD8452",
    "group_chat": "#55A868",
    "meeting":    "#C44E52",
    "file":       "#8172B2",
    "user":       "#937860",
    "storyline":  "#DA8BC3",
}

ENTITY_ORDER = ["email", "chat", "group_chat", "meeting", "file", "user", "storyline"]
CHANNEL_ORDER = ["email", "chat", "group_chat", "meeting"]

PALETTE = sns.color_palette("tab10")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent


def short_name(tenant_name: str, max_len: int = 14) -> str:
    s = tenant_name.split("-")[0]
    if len(s) < 3:
        s = tenant_name[:max_len]
        if len(tenant_name) > max_len:
            s = s + "…"
    return s


def load_yaml(path: Path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def parse_ts(ts_obj) -> float | None:
    """Parse a timestamp (string or datetime) to POSIX float."""
    from datetime import datetime, timezone
    if ts_obj is None:
        return None
    if isinstance(ts_obj, (int, float)):
        return float(ts_obj)
    if hasattr(ts_obj, "timestamp"):
        return ts_obj.timestamp()
    ts_str = str(ts_obj).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# A. Entity counts
# ---------------------------------------------------------------------------

def load_entity_counts(tenant_dir: Path) -> dict[str, int]:
    """Count entities in generation_log.json by type, plus users."""
    counts: dict[str, int] = defaultdict(int)

    gen_log = tenant_dir / "generation_log.json"
    if gen_log.exists():
        with open(gen_log, encoding="utf-8") as fh:
            for item in json.load(fh):
                etype = item.get("type", "unknown")
                counts[etype] += 1

    tenant_yaml = tenant_dir / "tenant.yaml"
    tenant_data = load_yaml(tenant_yaml)
    if isinstance(tenant_data, dict):
        counts["user"] += len(tenant_data.get("users", []))
    elif isinstance(tenant_data, list):
        counts["user"] += len(tenant_data)

    return dict(counts)


def load_eval_entity_counts(tenant_dir: Path) -> dict[str, int]:
    """Count eval test-case entities by entity_type from eval_dataset_log*.json."""
    counts: dict[str, int] = defaultdict(int)
    for log_path in sorted(tenant_dir.glob("eval_dataset_log*.json")):
        with open(log_path, encoding="utf-8") as fh:
            for item in json.load(fh):
                for ent in item.get("entity_list", []):
                    etype = ent.get("entity_type", "unknown")
                    counts[etype] += 1
    return dict(counts)


def plot_entity_stacked_bar(df: pd.DataFrame, title: str, save_path: Path) -> None:
    entity_types = [e for e in ENTITY_ORDER if e in df.columns]
    extra = [c for c in df.columns if c not in ENTITY_ORDER]
    entity_types += extra

    colors = [CHANNEL_COLORS.get(e, "#aaaaaa") for e in entity_types]

    fig, ax = plt.subplots(figsize=(10, 5))
    bottom = np.zeros(len(df))
    for etype, color in zip(entity_types, colors):
        if etype in df.columns:
            vals = df[etype].fillna(0).values
            ax.bar(df.index, vals, bottom=bottom, label=etype, color=color)
            bottom += vals

    ax.set_title(title, fontsize=13)
    ax.set_xlabel("Tenant")
    ax.set_ylabel("Count")
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(df.index, rotation=30, ha="right", fontsize=8)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_entity_heatmap(df: pd.DataFrame, title: str, save_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(max(8, len(df.columns) * 1.4), max(4, len(df) * 0.7)))
    sns.heatmap(
        df.T.fillna(0).astype(int),
        annot=True, fmt="d", cmap="YlOrRd",
        linewidths=0.5, ax=ax, cbar_kws={"label": "Count"},
    )
    ax.set_title(title, fontsize=13)
    ax.set_xlabel("Tenant")
    ax.set_ylabel("Entity Type")
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_entity_pies(df: pd.DataFrame, title: str, save_path: Path) -> None:
    n = len(df)
    ncols = min(n, 3)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4.5 * nrows))
    axes = np.array(axes).flatten()

    entity_types = [e for e in ENTITY_ORDER if e in df.columns]
    extra = [c for c in df.columns if c not in ENTITY_ORDER]
    entity_types += extra
    colors = [CHANNEL_COLORS.get(e, "#aaaaaa") for e in entity_types]

    for i, (tenant_label, row) in enumerate(df.iterrows()):
        ax = axes[i]
        vals = [row.get(e, 0) or 0 for e in entity_types]
        nonzero = [(v, e, c) for v, e, c in zip(vals, entity_types, colors) if v > 0]
        if nonzero:
            vs, es, cs = zip(*nonzero)
            ax.pie(vs, labels=es, colors=cs, autopct="%1.0f%%", startangle=90,
                   textprops={"fontsize": 7})
        ax.set_title(str(tenant_label), fontsize=9)

    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)

    fig.suptitle(title, fontsize=13)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


# ---------------------------------------------------------------------------
# B. IET summary (cross-tenant comparison)
# ---------------------------------------------------------------------------

def _collect_raw_iets(tenant_dir: Path) -> dict[str, list[float]]:
    """Return {channel: [iet_seconds, ...]} from config YAMLs."""
    from collections import defaultdict

    def sender_events(evs):
        by_sender: dict[str, list[float]] = defaultdict(list)
        for sender, ts in evs:
            if sender and ts is not None:
                by_sender[sender].append(ts)
        iets = []
        for tss in by_sender.values():
            s = sorted(tss)
            iets.extend(b - a for a, b in zip(s, s[1:]) if b > a)
        return iets

    result: dict[str, list[float]] = {}

    emails = load_yaml(tenant_dir / "config" / "emails.yaml")
    evs = [(m.get("from_user"), parse_ts(m.get("timestamp"))) for m in emails]
    result["email"] = sender_events(evs)

    chats = load_yaml(tenant_dir / "config" / "chats.yaml")
    evs = []
    for conv in chats:
        for msg in (conv.get("messages") or []):
            evs.append((msg.get("from_user"), parse_ts(msg.get("timestamp"))))
    result["chat"] = sender_events(evs)

    gchats = load_yaml(tenant_dir / "config" / "group_chats.yaml")
    evs = []
    for conv in gchats:
        for msg in (conv.get("messages") or []):
            evs.append((msg.get("from_user"), parse_ts(msg.get("timestamp"))))
    result["group_chat"] = sender_events(evs)

    meetings = load_yaml(tenant_dir / "config" / "meetings.yaml")
    evs = []
    for mtg in meetings:
        ts = parse_ts(mtg.get("start_time"))
        org = mtg.get("organizer", "")
        evs.append((org, ts))
        for att in (mtg.get("attendees") or []):
            if att != org:
                evs.append((att, ts))
    result["meeting"] = sender_events(evs)

    return result


def build_iet_data(
    tenant_dirs: list[Path],
    iet_summary_csv: Path,
) -> tuple[pd.DataFrame, dict[str, dict[str, list[float]]]]:
    """
    Returns (summary_df, raw_iets).
    summary_df has columns: tenant, channel, mean_iet_s, median_iet_s, …
    raw_iets: {tenant_name: {channel: [iet_s, ...]}}
    """
    if iet_summary_csv.exists():
        summary_df = pd.read_csv(iet_summary_csv)
    else:
        summary_df = pd.DataFrame()

    raw_iets: dict[str, dict[str, list[float]]] = {}
    for td in tenant_dirs:
        raw_iets[td.name] = _collect_raw_iets(td)

    return summary_df, raw_iets


def plot_iet_boxplots(raw_iets: dict[str, dict[str, list[float]]], save_path: Path) -> None:
    fig, axes = plt.subplots(1, len(CHANNEL_ORDER), figsize=(14, 5), sharey=False)
    for ax, channel in zip(axes, CHANNEL_ORDER):
        data = []
        labels = []
        for tenant_name, ch_data in raw_iets.items():
            iets = ch_data.get(channel, [])
            if iets:
                data.append(np.log10(np.array(iets) + 1))
                labels.append(short_name(tenant_name))
        if data:
            bp = ax.boxplot(data, patch_artist=True, notch=False)
            color = CHANNEL_COLORS.get(channel, "#888888")
            for patch in bp["boxes"]:
                patch.set_facecolor(color)
                patch.set_alpha(0.7)
            ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=7)
        ax.set_title(channel.replace("_", " ").title(), fontsize=10)
        ax.set_ylabel("log₁₀(IET + 1) [s]" if ax == axes[0] else "")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"10^{x:.0f}"))
    fig.suptitle("IET Distributions by Channel (Cross-Tenant)", fontsize=13)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_iet_mean_heatmap(summary_df: pd.DataFrame, save_path: Path) -> None:
    if summary_df.empty:
        return
    needed = {"tenant", "channel", "mean_iet_s"}
    if not needed.issubset(summary_df.columns):
        return
    pivot = summary_df.pivot_table(index="channel", columns="tenant", values="mean_iet_s")
    pivot.columns = [short_name(c) for c in pivot.columns]
    fig, ax = plt.subplots(figsize=(max(7, len(pivot.columns) * 1.5), 4))
    sns.heatmap(pivot, annot=True, fmt=".0f", cmap="Blues", linewidths=0.5,
                ax=ax, cbar_kws={"label": "Mean IET (s)"})
    ax.set_title("Mean IET per Channel per Tenant", fontsize=13)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


def plot_iet_grouped_bar(summary_df: pd.DataFrame, save_path: Path) -> None:
    if summary_df.empty or "tenant" not in summary_df.columns:
        return
    needed = {"tenant", "channel", "mean_iet_s"}
    if not needed.issubset(summary_df.columns):
        return
    df = summary_df.copy()
    df["tenant_short"] = df["tenant"].apply(short_name)
    fig, ax = plt.subplots(figsize=(11, 5))
    channels = [c for c in CHANNEL_ORDER if c in df["channel"].unique()]
    x = np.arange(len(df["tenant_short"].unique()))
    tenants = sorted(df["tenant_short"].unique())
    w = 0.8 / len(channels)
    for i, ch in enumerate(channels):
        sub = df[df["channel"] == ch].set_index("tenant_short")
        vals = [sub.loc[t, "mean_iet_s"] if t in sub.index else 0 for t in tenants]
        ax.bar(x + i * w, vals, w, label=ch, color=CHANNEL_COLORS.get(ch, "#888"))
    ax.set_xticks(x + w * (len(channels) - 1) / 2)
    ax.set_xticklabels(tenants, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Mean IET (s)")
    ax.set_title("Mean IET per Channel per Tenant", fontsize=13)
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


# ---------------------------------------------------------------------------
# C. Scale-free: power-law CCDF per channel per tenant
# ---------------------------------------------------------------------------

def fit_power_law_ccdf(arr: np.ndarray) -> tuple[float | None, float | None]:
    """OLS log-log CCDF fit. Returns (gamma, r2)."""
    if len(arr) < 5:
        return None, None
    sorted_arr = np.sort(arr)
    n = len(sorted_arr)
    ccdf = np.arange(n, 0, -1) / n
    t_min = np.median(sorted_arr)
    mask = sorted_arr >= t_min
    if mask.sum() < 3:
        return None, None
    log_t = np.log(sorted_arr[mask] + 1e-9)
    log_c = np.log(ccdf[mask] + 1e-12)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        coeffs = np.polyfit(log_t, log_c, 1)
    gamma = -coeffs[0]
    predicted = np.polyval(coeffs, log_t)
    ss_res = np.sum((log_c - predicted) ** 2)
    ss_tot = np.sum((log_c - log_c.mean()) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return round(float(gamma), 3), round(float(r2), 3)


def build_degree_sequence(tenant_dir: Path, channel: str) -> list[int]:
    """Return in-degree sequence for the directed graph of the given channel."""
    edges: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    if channel == "email":
        for msg in load_yaml(tenant_dir / "config" / "emails.yaml"):
            src = msg.get("from_user", "")
            for dst in (msg.get("to_users") or []):
                if src and dst:
                    edges[src][dst] += 1
    elif channel == "chat":
        for conv in load_yaml(tenant_dir / "config" / "chats.yaml"):
            for msg in (conv.get("messages") or []):
                src = msg.get("from_user", "")
                dst = msg.get("to_user", "")
                if src and dst:
                    edges[src][dst] += 1
    elif channel == "group_chat":
        for conv in load_yaml(tenant_dir / "config" / "group_chats.yaml"):
            parts = set(conv.get("participants") or [])
            for msg in (conv.get("messages") or []):
                src = msg.get("from_user", "")
                for dst in parts:
                    if dst != src:
                        edges[src][dst] += 1
    elif channel == "meeting":
        for mtg in load_yaml(tenant_dir / "config" / "meetings.yaml"):
            org = mtg.get("organizer", "")
            for att in (mtg.get("attendees") or []):
                if att and org:
                    edges[org][att] += 1

    # In-degree counts
    in_deg: Counter = Counter()
    for src, dsts in edges.items():
        for dst, w in dsts.items():
            in_deg[dst] += w
    return list(in_deg.values())


def plot_ccdf_per_tenant(
    tenant_dir: Path,
    tenant_label: str,
    save_path: Path,
) -> dict[str, tuple[float | None, float | None]]:
    """4-panel CCDF figure; returns {channel: (gamma, r2)}."""
    gammas: dict[str, tuple[float | None, float | None]] = {}
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    axes = axes.flatten()

    for ax, channel in zip(axes, CHANNEL_ORDER):
        degrees = build_degree_sequence(tenant_dir, channel)
        color = CHANNEL_COLORS.get(channel, "#888")
        if len(degrees) < 5:
            ax.text(0.5, 0.5, "Insufficient data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(channel.replace("_", " ").title())
            gammas[channel] = (None, None)
            continue

        arr = np.array(degrees, dtype=float)
        sorted_arr = np.sort(arr)
        n = len(sorted_arr)
        ccdf = np.arange(n, 0, -1) / n

        ax.step(sorted_arr, ccdf, color=color, linewidth=1.5, label="Empirical CCDF")
        ax.set_xscale("log")
        ax.set_yscale("log")

        gamma, r2 = fit_power_law_ccdf(arr)
        gammas[channel] = (gamma, r2)
        if gamma is not None:
            t_min = np.median(arr)
            mask = sorted_arr >= t_min
            log_t = np.log(sorted_arr[mask] + 1e-9)
            log_c = np.log(ccdf[mask] + 1e-12)
            coeffs = np.polyfit(log_t, log_c, 1)
            fit_line = np.exp(np.polyval(coeffs, np.log(sorted_arr[mask] + 1e-9)))
            ax.plot(sorted_arr[mask], fit_line, "--", color="black",
                    linewidth=1, label=f"Power law γ={gamma:.2f} (R²={r2:.2f})")

        ax.set_title(channel.replace("_", " ").title(), fontsize=10)
        ax.set_xlabel("In-degree")
        ax.set_ylabel("CCDF")
        ax.legend(fontsize=7)

    fig.suptitle(f"In-degree CCDF – {tenant_label}", fontsize=13)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")
    return gammas


def plot_cross_tenant_gamma(
    gamma_data: dict[str, dict[str, tuple[float | None, float | None]]],
    save_path: Path,
) -> None:
    """Grouped bar chart: gamma exponent per (channel × tenant)."""
    tenants = list(gamma_data.keys())
    channels = CHANNEL_ORDER

    x = np.arange(len(tenants))
    w = 0.8 / len(channels)

    fig, ax = plt.subplots(figsize=(11, 5))
    for i, ch in enumerate(channels):
        vals = []
        for t in tenants:
            g, _ = gamma_data[t].get(ch, (None, None))
            vals.append(g if g is not None else 0.0)
        ax.bar(x + i * w, vals, w, label=ch, color=CHANNEL_COLORS.get(ch, "#888"))

    ax.set_xticks(x + w * (len(channels) - 1) / 2)
    ax.set_xticklabels([short_name(t) for t in tenants], rotation=30, ha="right", fontsize=8)
    ax.axhline(2.0, color="grey", linestyle="--", linewidth=0.8, label="γ = 2 (scale-free)")
    ax.set_ylabel("Power-law exponent γ")
    ax.set_title("Scale-free Exponent γ per Channel per Tenant", fontsize=13)
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


# ---------------------------------------------------------------------------
# D. File author Zipf distribution
# ---------------------------------------------------------------------------

def plot_zipf(tenant_dirs: list[Path], save_path: Path) -> None:
    n = len(tenant_dirs)
    ncols = min(n, 3)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4.5 * nrows))
    axes = np.array(axes).flatten()

    for i, td in enumerate(tenant_dirs):
        ax = axes[i]
        files = load_yaml(td / "config" / "files.yaml")
        counts = Counter(f.get("created_by", "unknown") for f in files)
        if not counts:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(short_name(td.name))
            continue
        sorted_counts = sorted(counts.values(), reverse=True)
        ranks = np.arange(1, len(sorted_counts) + 1)
        ax.scatter(np.log10(ranks), np.log10(sorted_counts),
                   s=30, color=CHANNEL_COLORS["file"], alpha=0.8)
        # Zipf fit
        if len(sorted_counts) > 2:
            log_r = np.log10(ranks)
            log_c = np.log10(sorted_counts)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                coeffs = np.polyfit(log_r, log_c, 1)
            fit_y = np.polyval(coeffs, log_r)
            ax.plot(log_r, fit_y, "--", color="black", linewidth=1,
                    label=f"slope={coeffs[0]:.2f}")
            ax.legend(fontsize=8)
        ax.set_title(short_name(td.name), fontsize=10)
        ax.set_xlabel("log₁₀(rank)")
        ax.set_ylabel("log₁₀(count)")

    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("File Author Distribution (Zipf/Power-law)", fontsize=13)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {save_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Data distribution analysis for EABench")
    parser.add_argument(
        "--tenants-dir",
        default=str(REPO_ROOT / "examples" / "tenants"),
        help="Path to tenants directory",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "analyze" / "output" / "data_distribution"),
        help="Root directory for figures and data",
    )
    args = parser.parse_args(argv)

    tenants_dir = Path(args.tenants_dir)
    output_dir = Path(args.output_dir)
    fig_dir = output_dir / "figures"
    data_dir = output_dir / "data"
    fig_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    tenant_dirs = sorted(
        [d for d in tenants_dir.iterdir() if d.is_dir()],
        key=lambda p: p.name,
    )
    if not tenant_dirs:
        print("No tenant directories found. Exiting.", file=sys.stderr)
        sys.exit(1)

    tenant_labels = [short_name(td.name) for td in tenant_dirs]

    # ------------------------------------------------------------------
    # A. Entity counts
    # ------------------------------------------------------------------
    print("\n=== A. Entity counts ===")

    gen_rows: dict[str, dict[str, int]] = {}
    eval_rows: dict[str, dict[str, int]] = {}
    summary_rows: list[dict] = []

    for td in tenant_dirs:
        label = short_name(td.name)
        ec = load_entity_counts(td)
        gen_rows[label] = ec
        ev = load_eval_entity_counts(td)
        eval_rows[label] = ev
        for etype, cnt in {**ec, **ev}.items():
            summary_rows.append({"tenant": td.name, "entity_type": etype, "count": cnt,
                                  "source": "generation" if etype in ec else "eval"})

    gen_df = pd.DataFrame(gen_rows).T.fillna(0).astype(int)
    eval_df = pd.DataFrame(eval_rows).T.fillna(0).astype(int)

    plot_entity_stacked_bar(gen_df, "Entity Counts per Tenant (Generation Log)",
                            fig_dir / "entity_counts_generation.pdf")
    plot_entity_stacked_bar(eval_df, "Eval Test Cases by Entity Type per Tenant",
                            fig_dir / "entity_counts_eval.pdf")
    plot_entity_heatmap(gen_df, "Entity Count Heatmap (Generation Log)",
                        fig_dir / "entity_heatmap_generation.pdf")
    plot_entity_heatmap(eval_df, "Eval Entity Count Heatmap",
                        fig_dir / "entity_heatmap_eval.pdf")
    plot_entity_pies(gen_df, "Entity Type Breakdown per Tenant",
                     fig_dir / "entity_pies.pdf")

    # Save summary CSV
    summary_csv = data_dir / "entity_summary.csv"
    pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)
    print(f"  Saved: {summary_csv}")

    # ------------------------------------------------------------------
    # B. IET summary
    # ------------------------------------------------------------------
    print("\n=== B. IET summary ===")

    iet_csv = REPO_ROOT / "analyze" / "output" / "inter_event_times" / "data" / "iet_summary.csv"
    iet_summary_df, raw_iets = build_iet_data(tenant_dirs, iet_csv)

    plot_iet_boxplots(raw_iets, fig_dir / "iet_boxplots_cross_tenant.pdf")
    plot_iet_mean_heatmap(iet_summary_df, fig_dir / "iet_mean_heatmap.pdf")
    plot_iet_grouped_bar(iet_summary_df, fig_dir / "iet_grouped_bar.pdf")

    # ------------------------------------------------------------------
    # C. Scale-free
    # ------------------------------------------------------------------
    print("\n=== C. Scale-free properties ===")

    gamma_data: dict[str, dict[str, tuple[float | None, float | None]]] = {}
    for td in tenant_dirs:
        label = td.name
        save_path = fig_dir / f"{td.name}_ccdf_per_channel.pdf"
        gammas = plot_ccdf_per_tenant(td, short_name(td.name), save_path)
        gamma_data[label] = gammas

    plot_cross_tenant_gamma(gamma_data, fig_dir / "cross_tenant_gamma_exponents.pdf")

    # Save gamma CSV
    gamma_rows = []
    for tenant_name, ch_gammas in gamma_data.items():
        for ch, (g, r2) in ch_gammas.items():
            gamma_rows.append({"tenant": tenant_name, "channel": ch,
                                "gamma": g, "r2": r2})
    pd.DataFrame(gamma_rows).to_csv(data_dir / "gamma_exponents.csv", index=False)
    print(f"  Saved: {data_dir / 'gamma_exponents.csv'}")

    # ------------------------------------------------------------------
    # D. Zipf
    # ------------------------------------------------------------------
    print("\n=== D. File author Zipf ===")
    plot_zipf(tenant_dirs, fig_dir / "file_author_zipf.pdf")

    # ------------------------------------------------------------------
    # E. Cross-tenant summary table
    # ------------------------------------------------------------------
    print("\n=== E. Summary CSV ===")
    # Flatten gen_df and eval_df into one wide-format summary
    gen_flat = gen_df.reset_index().melt(id_vars="index", var_name="entity_type", value_name="count")
    gen_flat.columns = ["tenant", "entity_type", "count"]
    gen_flat["source"] = "generation"

    eval_flat = eval_df.reset_index().melt(id_vars="index", var_name="entity_type", value_name="count")
    eval_flat.columns = ["tenant", "entity_type", "count"]
    eval_flat["source"] = "eval"

    cross_tenant = pd.concat([gen_flat, eval_flat], ignore_index=True)
    cross_tenant = cross_tenant[cross_tenant["count"] > 0]
    ct_path = data_dir / "cross_tenant_summary.csv"
    cross_tenant.to_csv(ct_path, index=False)
    print(f"  Saved: {ct_path}")

    print("\nDone. All figures in:", fig_dir)
    print("All data in:", data_dir)


if __name__ == "__main__":
    main()
