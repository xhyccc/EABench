"""
03_inter_event_times.py
=======================
Inter-event time (IET) analysis for EABench tenant communications.

Barabási et al. showed that human communication is fundamentally bursty: the
distribution of inter-event times (time gaps between successive messages from
the same sender) follows a heavy-tail / power-law distribution rather than a
Poisson process.  This script replicates that analysis across tenants and
communication channel types.

For each (tenant, channel) pair the script:
  * Extracts all timestamped events and sorts them per sender.
  * Computes inter-event times (IET) in seconds between consecutive events.
  * Fits two heavy-tail models:
      - Power law:  P(τ) ~ τ^(-α)
      - Log-normal: P(τ) ~ LogNormal(μ, σ)
  * Generates:
      - Log-log survival (CCDF) plots with model overlays
      - Bursty-coefficient B = (σ_IET - μ_IET) / (σ_IET + μ_IET)   [-1, +1]
        (B > 0 → bursty, B < 0 → regular, B ≈ 0 → Poisson)
      - Memory coefficient M ∈ [-1, 1] measuring autocorrelation of IETs
  * Saves per-tenant IET CSV files and a summary table.

Usage
-----
    python analyze/03_inter_event_times.py \
        --tenants-dir examples/tenants \
        --output-dir  analyze/output/inter_event_times
"""

import argparse
import csv
import sys
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml
from scipy.stats import lognorm, ks_2samp
from scipy.optimize import curve_fit


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def parse_ts(ts_str: str) -> float | None:
    """Return POSIX timestamp (float seconds) from an ISO-8601 string."""
    if not ts_str:
        return None
    # Handle both 'Z' suffix and '+00:00' style
    ts_str = ts_str.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Event extraction per channel
# ---------------------------------------------------------------------------

def load_yaml(path: Path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def events_from_emails(emails: list) -> list[tuple[str, float, str]]:
    """Return list of (sender_id, posix_ts, channel)."""
    evs = []
    for msg in emails:
        sender = msg.get("from_user", "")
        ts = parse_ts(str(msg.get("timestamp", "")))
        if sender and ts is not None:
            evs.append((sender, ts, "email"))
    return evs


def events_from_chats(chats: list) -> list[tuple[str, float, str]]:
    evs = []
    for conv in chats:
        for msg in (conv.get("messages") or []):
            sender = msg.get("from_user", "")
            ts = parse_ts(str(msg.get("timestamp", "")))
            if sender and ts is not None:
                evs.append((sender, ts, "chat"))
    return evs


def events_from_group_chats(gchats: list) -> list[tuple[str, float, str]]:
    evs = []
    for conv in gchats:
        for msg in (conv.get("messages") or []):
            sender = msg.get("from_user", "")
            ts = parse_ts(str(msg.get("timestamp", "")))
            if sender and ts is not None:
                evs.append((sender, ts, "group_chat"))
    return evs


def events_from_meetings(meetings: list) -> list[tuple[str, float, str]]:
    evs = []
    for mtg in meetings:
        org = mtg.get("organizer", "")
        ts = parse_ts(str(mtg.get("start_time", "")))
        if org and ts is not None:
            evs.append((org, ts, "meeting"))
        for att in (mtg.get("attendees") or []):
            if att != org and ts is not None:
                evs.append((att, ts, "meeting"))
    return evs


# ---------------------------------------------------------------------------
# IET computation
# ---------------------------------------------------------------------------

def compute_iets(events: list[tuple[str, float, str]]) -> dict[str, list[float]]:
    """
    Given a flat list of (sender, posix_ts, channel) events,
    group by sender and compute intra-sender IETs.
    Returns {sender: [iet_seconds, ...]} (only senders with ≥ 2 events).
    """
    per_sender: dict[str, list[float]] = defaultdict(list)
    for sender, ts, _ in events:
        per_sender[sender].append(ts)

    iets: dict[str, list[float]] = {}
    for sender, timestamps in per_sender.items():
        sorted_ts = sorted(timestamps)
        diffs = [sorted_ts[i + 1] - sorted_ts[i]
                 for i in range(len(sorted_ts) - 1)
                 if sorted_ts[i + 1] > sorted_ts[i]]
        if diffs:
            iets[sender] = diffs
    return iets


# ---------------------------------------------------------------------------
# Statistical characterisation
# ---------------------------------------------------------------------------

def burstiness(iets: list[float]) -> float:
    """Goh & Barabási burstiness parameter B ∈ [-1, 1]."""
    arr = np.array(iets)
    mu, sigma = arr.mean(), arr.std()
    denom = sigma + mu
    if denom == 0:
        return 0.0
    return float((sigma - mu) / denom)


def memory_coefficient(iets: list[float]) -> float:
    """
    Memory coefficient M: Pearson correlation between consecutive IETs.
    Ranges in [-1, 1]; M > 0 → clustered bursts, M < 0 → alternating.
    """
    arr = np.array(iets)
    if len(arr) < 3:
        return 0.0
    x, y = arr[:-1], arr[1:]
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def fit_power_law_iet(iets: np.ndarray):
    """Fit P(τ) ~ τ^(-α) via OLS on log-log CCDF. Returns (alpha, r2)."""
    sorted_iet = np.sort(iets)
    n = len(sorted_iet)
    ccdf = (np.arange(n, 0, -1)) / n  # empirical CCDF

    # Use only τ > τ_min (τ_min = median as heuristic)
    t_min = np.median(sorted_iet)
    mask = sorted_iet >= t_min
    if mask.sum() < 3:
        return None, None

    log_t = np.log(sorted_iet[mask])
    log_c = np.log(ccdf[mask] + 1e-12)

    coeffs = np.polyfit(log_t, log_c, 1)
    alpha = -coeffs[0]

    predicted = np.polyval(coeffs, log_t)
    ss_res = np.sum((log_c - predicted) ** 2)
    ss_tot = np.sum((log_c - log_c.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return round(float(alpha), 3), round(float(r2), 3)


def fit_lognormal_iet(iets: np.ndarray):
    """Fit log-normal to IETs. Returns (mu, sigma, ks_p_value)."""
    if len(iets) < 5:
        return None, None, None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        shape, loc, scale = lognorm.fit(iets, floc=0)
    sigma = shape
    mu = np.log(scale)
    # KS goodness-of-fit
    _, p = ks_2samp(iets, lognorm.rvs(shape, loc=loc, scale=scale,
                                       size=len(iets), random_state=42))
    return round(float(mu), 3), round(float(sigma), 3), round(float(p), 4)


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

CHANNEL_COLORS = {
    "email":      "#4E79A7",
    "chat":       "#F28E2B",
    "group_chat": "#59A14F",
    "meeting":    "#E15759",
}


def plot_iet_ccdf(channel_iets: dict[str, list[float]],
                  title: str, out_path: Path):
    """Log-log CCDF plot overlaying multiple channels."""
    fig, ax = plt.subplots(figsize=(9, 6))
    has_data = False

    for ch, iets in channel_iets.items():
        if not iets:
            continue
        arr = np.sort(np.array(iets))
        n = len(arr)
        ccdf = np.arange(n, 0, -1) / n
        color = CHANNEL_COLORS.get(ch, "#999999")
        ax.step(arr, ccdf, where="post", color=color, lw=2,
                label=f"{ch} (n={n})")

        # Power-law fit overlay
        alpha, r2 = fit_power_law_iet(arr)
        if alpha is not None and r2 is not None and r2 > 0.5:
            t_min = np.median(arr)
            t_line = np.linspace(t_min, arr.max(), 200)
            # Normalise CCDF at t_min
            ccdf_at_tmin = ccdf[arr >= t_min].max() if (arr >= t_min).any() else 1.0
            c_line = ccdf_at_tmin * (t_line / t_min) ** (-alpha)
            ax.plot(t_line, c_line, "--", color=color, lw=1.2, alpha=0.7,
                    label=f"  PL fit α={alpha:.2f} (R²={r2:.2f})")
        has_data = True

    if not has_data:
        plt.close(fig)
        return

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Inter-event time τ (seconds)")
    ax.set_ylabel("P(T ≥ τ)")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_iet_histogram(iets: list[float], channel: str,
                       title: str, out_path: Path):
    """Linear-scale histogram + log-normal overlay."""
    if not iets:
        return
    arr = np.array(iets)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    # Linear histogram
    axes[0].hist(arr, bins=30, density=True,
                 color=CHANNEL_COLORS.get(channel, "#4E79A7"), alpha=0.8)
    axes[0].set_xlabel("IET (seconds)")
    axes[0].set_ylabel("Density")
    axes[0].set_title("Linear scale")

    # Log-scale histogram
    log_arr = np.log1p(arr)
    axes[1].hist(log_arr, bins=30, density=True,
                 color=CHANNEL_COLORS.get(channel, "#4E79A7"), alpha=0.8)
    mu_ln, s_ln, _ = fit_lognormal_iet(arr) or (None, None, None)
    if mu_ln is not None and s_ln is not None:
        x = np.linspace(log_arr.min(), log_arr.max(), 200)
        from scipy.stats import norm
        axes[1].plot(x, norm.pdf(x, mu_ln, s_ln), "r--", lw=2,
                     label=f"LogNormal μ={mu_ln:.2f} σ={s_ln:.2f}")
        axes[1].legend()
    axes[1].set_xlabel("log(1 + IET)")
    axes[1].set_ylabel("Density")
    axes[1].set_title("Log-scale histogram")

    fig.suptitle(title, fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_burstiness_summary(rows: list[dict], out_path: Path):
    """Heatmap of burstiness coefficient B across (tenant × channel)."""
    tenants = sorted({r["tenant"] for r in rows})
    channels = sorted({r["channel"] for r in rows})

    B_matrix = np.full((len(channels), len(tenants)), np.nan)
    for r in rows:
        ti = tenants.index(r["tenant"])
        ci = channels.index(r["channel"])
        b = r.get("burstiness")
        if b is not None:
            B_matrix[ci, ti] = float(b)

    fig, ax = plt.subplots(figsize=(max(6, len(tenants) * 2), max(4, len(channels) * 1.2)))
    im = ax.imshow(B_matrix, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    plt.colorbar(im, ax=ax, label="Burstiness B")

    short_t = [t.split("-")[0] + "…" if len(t) > 12 else t for t in tenants]
    ax.set_xticks(range(len(tenants)))
    ax.set_xticklabels(short_t, rotation=30, ha="right")
    ax.set_yticks(range(len(channels)))
    ax.set_yticklabels(channels)
    ax.set_title("Burstiness Coefficient B per (Tenant × Channel)", fontweight="bold")

    # Annotate cells
    for i in range(len(channels)):
        for j in range(len(tenants)):
            v = B_matrix[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                        fontsize=8, color="black")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CHANNELS = {
    "email":      ("emails.yaml",      events_from_emails),
    "chat":       ("chats.yaml",       events_from_chats),
    "group_chat": ("group_chats.yaml", events_from_group_chats),
    "meeting":    ("meetings.yaml",    events_from_meetings),
}


def process_tenant(tenant_dir: Path, out_dir: Path) -> list[dict]:
    name = tenant_dir.name
    cfg = tenant_dir / "config"
    if not cfg.exists():
        return []

    fig_dir = out_dir / "figures"
    data_dir = out_dir / "data"
    fig_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Collect IETs per channel
    channel_iets: dict[str, list[float]] = {}
    all_rows: list[dict] = []
    all_iet_records = []

    for ch, (fname, loader) in CHANNELS.items():
        fpath = cfg / fname
        if not fpath.exists():
            continue
        data = load_yaml(fpath)
        events = loader(data)
        per_sender = compute_iets(events)

        flat_iets = [t for iets in per_sender.values() for t in iets]
        channel_iets[ch] = flat_iets

        if not flat_iets:
            continue

        arr = np.array(flat_iets)
        alpha, r2_pl = fit_power_law_iet(arr)
        mu_ln, sigma_ln, ks_p = fit_lognormal_iet(arr)
        B = burstiness(flat_iets)
        M = memory_coefficient(flat_iets)

        row = {
            "tenant": name,
            "channel": ch,
            "num_events": len(events),
            "num_senders": len(per_sender),
            "num_iets": len(flat_iets),
            "mean_iet_s": round(float(arr.mean()), 1),
            "median_iet_s": round(float(np.median(arr)), 1),
            "std_iet_s": round(float(arr.std()), 1),
            "burstiness": round(B, 4),
            "memory": round(M, 4),
            "powerlaw_alpha": alpha,
            "powerlaw_r2": r2_pl,
            "lognormal_mu": mu_ln,
            "lognormal_sigma": sigma_ln,
            "lognormal_ks_p": ks_p,
        }
        all_rows.append(row)

        # Per-channel histogram
        plot_iet_histogram(
            flat_iets, ch,
            title=f"IET Histogram ({ch}) — {name}",
            out_path=fig_dir / f"{name}_{ch}_iet_hist.pdf",
        )

        # Save per-sender IETs to CSV
        for sender, iets in per_sender.items():
            for iet in iets:
                all_iet_records.append({
                    "tenant": name, "channel": ch,
                    "sender": sender, "iet_seconds": round(iet, 1),
                })

    # Multi-channel CCDF overlay
    if channel_iets:
        plot_iet_ccdf(
            channel_iets,
            title=f"IET CCDF (all channels) — {name}",
            out_path=fig_dir / f"{name}_iet_ccdf.pdf",
        )

    # Write raw IET CSV
    if all_iet_records:
        csv_path = data_dir / f"{name}_iets.csv"
        keys = ["tenant", "channel", "sender", "iet_seconds"]
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_iet_records)

    return all_rows


def main():
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Inter-event time analysis for EABench tenants.")
    parser.add_argument("--tenants-dir",
                        default=str(repo_root / "examples" / "tenants"))
    parser.add_argument("--output-dir",
                        default=str(repo_root / "analyze" / "output" / "inter_event_times"))
    args = parser.parse_args()

    tenants_dir = Path(args.tenants_dir)
    out_dir = Path(args.output_dir)

    if not tenants_dir.exists():
        sys.exit(f"Tenants directory not found: {tenants_dir}")

    tenant_dirs = sorted([d for d in tenants_dir.iterdir() if d.is_dir()])
    print(f"Found {len(tenant_dirs)} tenant(s)")

    summary_rows: list[dict] = []
    for td in tenant_dirs:
        print(f"\nProcessing: {td.name}")
        rows = process_tenant(td, out_dir)
        for r in rows:
            print(f"  [{r['channel']}] n_iets={r['num_iets']}, "
                  f"B={r['burstiness']:.3f}, M={r['memory']:.3f}, "
                  f"α={r['powerlaw_alpha']}")
        summary_rows.extend(rows)

    # Write summary CSV
    if summary_rows:
        csv_path = out_dir / "data" / "iet_summary.csv"
        (out_dir / "data").mkdir(parents=True, exist_ok=True)
        keys = list(summary_rows[0].keys())
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            writer.writerows(summary_rows)
        print(f"\nSummary saved to: {csv_path}")

        # Burstiness heatmap
        plot_burstiness_summary(
            summary_rows,
            out_path=out_dir / "figures" / "burstiness_heatmap.pdf",
        )

    # Cross-channel IET comparison plot
    if summary_rows:
        fig, axes = plt.subplots(1, 2, figsize=(13, 5))
        channels = sorted({r["channel"] for r in summary_rows})
        for ch in channels:
            ch_rows = [r for r in summary_rows if r["channel"] == ch]
            if not ch_rows:
                continue
            tenants = [r["tenant"].split("-")[0] for r in ch_rows]
            bs = [r["burstiness"] for r in ch_rows]
            ms = [r["memory"] for r in ch_rows]
            color = CHANNEL_COLORS.get(ch, "#999999")
            axes[0].scatter(tenants, bs, label=ch, color=color, s=80)
            axes[1].scatter(tenants, ms, label=ch, color=color, s=80)

        axes[0].axhline(0, color="gray", lw=1, linestyle="--")
        axes[0].set_ylabel("Burstiness B")
        axes[0].set_title("Burstiness per tenant & channel")
        axes[0].legend(fontsize=8)
        axes[0].tick_params(axis="x", rotation=30)

        axes[1].axhline(0, color="gray", lw=1, linestyle="--")
        axes[1].set_ylabel("Memory M")
        axes[1].set_title("Memory coefficient per tenant & channel")
        axes[1].legend(fontsize=8)
        axes[1].tick_params(axis="x", rotation=30)

        fig.suptitle("Burstiness & Memory across Tenants and Channels",
                     fontsize=12, fontweight="bold")
        fig.tight_layout()
        fig.savefig(out_dir / "figures" / "burstiness_memory_overview.pdf", dpi=150)
        plt.close(fig)

    print("\nDone. Output written to:", out_dir)


if __name__ == "__main__":
    main()
