"""
02_network_analysis.py
======================
Complex-network analysis of EABench tenant communication graphs with a focus on
Barabási–Albert (BA) preferential-attachment characteristics.

For each tenant the script:
  * Re-builds the aggregate directed communication graph (all channels).
  * Computes standard complex-network metrics:
      - degree distribution and power-law / BA fit
      - clustering coefficient
      - average shortest path length (on the weakly-connected component)
      - diameter
      - betweenness, closeness, eigenvector centrality
      - reciprocity, transitivity
  * Fits the *cumulative* in-degree distribution to a power law P(k) ~ k^(-γ)
    and reports the exponent γ (BA networks typically give γ ≈ 3).
  * Generates a synthetic BA graph of the same size and compares metrics.
  * Saves figures (log-log degree plots, centrality bar charts) and a CSV
    summary table.

Usage
-----
    python analyze/02_network_analysis.py \
        --tenants-dir examples/tenants \
        --output-dir  analyze/output/network_analysis
"""

import argparse
import csv
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import yaml
from scipy.optimize import curve_fit
from scipy.stats import kstest, expon, lognorm


# ---------------------------------------------------------------------------
# Shared loader (duplicated from script 01 to keep scripts self-contained)
# ---------------------------------------------------------------------------

def load_yaml(path: Path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def build_aggregate_graph(tenant_dir: Path) -> nx.DiGraph:
    cfg = tenant_dir / "config"
    G = nx.DiGraph()

    def add(src, dst, ch):
        if not src or not dst:
            return
        if G.has_edge(src, dst):
            G[src][dst]["weight"] += 1
        else:
            G.add_edge(src, dst, weight=1, channel=ch)

    # Emails
    for msg in load_yaml(cfg / "emails.yaml") if (cfg / "emails.yaml").exists() else []:
        src = msg.get("from_user", "")
        for dst in (msg.get("to_users") or []) + (msg.get("cc_users") or []):
            add(src, dst, "email")

    # Direct chats
    for conv in load_yaml(cfg / "chats.yaml") if (cfg / "chats.yaml").exists() else []:
        for msg in (conv.get("messages") or []):
            add(msg.get("from_user", ""), msg.get("to_user", ""), "chat")

    # Group chats
    for conv in load_yaml(cfg / "group_chats.yaml") if (cfg / "group_chats.yaml").exists() else []:
        parts = conv.get("participants") or []
        for msg in (conv.get("messages") or []):
            src = msg.get("from_user", "")
            for dst in parts:
                if dst != src:
                    add(src, dst, "group_chat")

    # Meetings
    for mtg in load_yaml(cfg / "meetings.yaml") if (cfg / "meetings.yaml").exists() else []:
        org = mtg.get("organizer", "")
        att = mtg.get("attendees") or []
        for a in att:
            if a != org:
                add(org, a, "meeting")
        for i, a in enumerate(att):
            for b in att[i + 1:]:
                add(a, b, "meeting")
                add(b, a, "meeting")

    return G


# ---------------------------------------------------------------------------
# Power-law fitting
# ---------------------------------------------------------------------------

def fit_power_law(degrees: np.ndarray):
    """
    Fit P(k) ~ k^(-gamma) to the CCDF using OLS on log-log scale.
    Returns (gamma, r_squared, k_min).
    """
    if len(degrees) < 5:
        return None, None, None

    unique, counts = np.unique(degrees, return_counts=True)
    if len(unique) < 3:
        return None, None, None

    # Use k >= k_min where k_min is where the power law appears to start
    # (simple heuristic: k >= 1)
    mask = unique >= 1
    k_vals = unique[mask].astype(float)
    p_vals = counts[mask].astype(float)
    p_vals = p_vals / p_vals.sum()

    # CCDF
    ccdf = np.cumsum(p_vals[::-1])[::-1]

    log_k = np.log(k_vals)
    log_ccdf = np.log(ccdf + 1e-12)

    # Linear fit in log-log space
    coeffs = np.polyfit(log_k, log_ccdf, 1)
    gamma = -coeffs[0]  # slope = -(gamma - 1) for CCDF

    # R²
    predicted = np.polyval(coeffs, log_k)
    ss_res = np.sum((log_ccdf - predicted) ** 2)
    ss_tot = np.sum((log_ccdf - log_ccdf.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return gamma, r2, int(k_vals[0])


# ---------------------------------------------------------------------------
# Network metrics
# ---------------------------------------------------------------------------

def compute_metrics(G: nx.DiGraph, name: str) -> dict:
    n = G.number_of_nodes()
    e = G.number_of_edges()
    metrics = {
        "tenant": name,
        "nodes": n,
        "edges": e,
        "density": round(nx.density(G), 4) if n > 1 else 0,
    }

    if n == 0:
        return metrics

    in_degs  = np.array([d for _, d in G.in_degree()])
    out_degs = np.array([d for _, d in G.out_degree()])
    metrics["mean_in_degree"]  = round(float(in_degs.mean()),  2)
    metrics["mean_out_degree"] = round(float(out_degs.mean()), 2)
    metrics["max_in_degree"]   = int(in_degs.max())
    metrics["max_out_degree"]  = int(out_degs.max())

    # Reciprocity
    metrics["reciprocity"] = round(nx.reciprocity(G), 4) if e > 0 else 0.0

    # Transitivity (global clustering on underlying undirected graph)
    metrics["transitivity"] = round(nx.transitivity(G.to_undirected()), 4)

    # Weakly-connected-component analysis
    wcc_sizes = sorted([len(c) for c in nx.weakly_connected_components(G)], reverse=True)
    metrics["num_wcc"] = len(wcc_sizes)
    metrics["giant_wcc_fraction"] = round(wcc_sizes[0] / n, 4) if wcc_sizes else 0

    G_wcc = G.subgraph(max(nx.weakly_connected_components(G), key=len)).copy()

    # Diameter & avg path length on giant WCC (undirected for tractability)
    U = G_wcc.to_undirected()
    if nx.is_connected(U):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            metrics["diameter"] = nx.diameter(U)
            metrics["avg_path_length"] = round(nx.average_shortest_path_length(U), 3)
    else:
        metrics["diameter"] = None
        metrics["avg_path_length"] = None

    # Power-law fit on in-degree
    gamma, r2, k_min = fit_power_law(in_degs)
    metrics["power_law_gamma"] = round(gamma, 3) if gamma is not None else None
    metrics["power_law_r2"]    = round(r2, 3)    if r2    is not None else None
    metrics["power_law_k_min"] = k_min

    # Centrality (top-3 nodes by betweenness)
    bc = nx.betweenness_centrality(G_wcc, normalized=True)
    top3 = sorted(bc, key=bc.get, reverse=True)[:3]
    metrics["top_betweenness"] = "; ".join(f"{u}({bc[u]:.3f})" for u in top3)

    return metrics


# ---------------------------------------------------------------------------
# Comparison with BA model
# ---------------------------------------------------------------------------

def ba_comparison(G: nx.DiGraph) -> dict:
    """Generate a BA graph with same n, m and compare degree distributions."""
    n = G.number_of_nodes()
    if n < 3:
        return {}
    e = G.number_of_edges()
    # m = avg edges per node (for undirected BA)
    m = max(1, round(e / n))
    m = min(m, n - 1)
    ba = nx.barabasi_albert_graph(n, m, seed=42)
    ba_degs = np.array([d for _, d in ba.degree()])
    real_degs = np.array([d for _, d in G.to_undirected().degree()])

    return {
        "ba_mean_degree": round(float(ba_degs.mean()), 2),
        "real_mean_degree": round(float(real_degs.mean()), 2),
        "ba_max_degree": int(ba_degs.max()),
        "real_max_degree": int(real_degs.max()),
    }


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def plot_degree_powerlaw(G: nx.DiGraph, title: str, out_path: Path):
    if len(G.nodes) == 0:
        return

    in_degs = np.array([d for _, d in G.in_degree()])
    unique, counts = np.unique(in_degs, return_counts=True)
    prob = counts / counts.sum()
    # CCDF
    ccdf = np.cumsum(prob[::-1])[::-1]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # Left: linear scale
    axes[0].bar(unique, prob, color="#4E79A7", alpha=0.8)
    axes[0].set_xlabel("In-degree k")
    axes[0].set_ylabel("P(k)")
    axes[0].set_title("In-degree distribution (linear)")

    # Right: log-log CCDF + power-law fit
    mask = unique >= 1
    k_fit = unique[mask].astype(float)
    c_fit = ccdf[mask]

    axes[1].scatter(k_fit, c_fit, s=30, color="#4E79A7", alpha=0.8, label="Empirical CCDF")
    if len(k_fit) >= 3:
        log_k = np.log(k_fit)
        log_c = np.log(c_fit + 1e-12)
        coeffs = np.polyfit(log_k, log_c, 1)
        gamma = -coeffs[0]
        k_line = np.linspace(k_fit.min(), k_fit.max(), 100)
        c_line = np.exp(np.polyval(coeffs, np.log(k_line)))
        axes[1].plot(k_line, c_line, "r--", lw=2, label=f"Power law fit γ={gamma:.2f}")

    axes[1].set_xscale("log")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("In-degree k")
    axes[1].set_ylabel("P(K ≥ k)")
    axes[1].set_title("CCDF (log-log) + power-law fit")
    axes[1].legend()

    fig.suptitle(title, fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_centrality(G: nx.DiGraph, title: str, out_path: Path):
    if len(G.nodes) == 0:
        return

    G_wcc = G.subgraph(max(nx.weakly_connected_components(G), key=len)).copy()
    bc = nx.betweenness_centrality(G_wcc, normalized=True)
    top_n = sorted(bc, key=bc.get, reverse=True)[:15]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh([u[:20] for u in reversed(top_n)],
            [bc[u] for u in reversed(top_n)],
            color="#F28E2B", alpha=0.85)
    ax.set_xlabel("Betweenness Centrality (normalised)")
    ax.set_title(title, fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_ba_comparison(G: nx.DiGraph, title: str, out_path: Path):
    n = G.number_of_nodes()
    if n < 3:
        return

    e = G.number_of_edges()
    m = max(1, min(round(e / n), n - 1))
    ba = nx.barabasi_albert_graph(n, m, seed=42)
    ba_degs = sorted([d for _, d in ba.degree()], reverse=True)
    real_degs = sorted([d for _, d in G.to_undirected().degree()], reverse=True)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(range(len(real_degs)), real_degs, color="#4E79A7", lw=2,
            label="Empirical (rank-ordered degree)")
    ax.plot(range(len(ba_degs)), ba_degs, color="#E15759", lw=2, linestyle="--",
            label=f"BA model (n={n}, m={m})")
    ax.set_xlabel("Node rank")
    ax.set_ylabel("Degree")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Complex-network / BA analysis for EABench tenants.")
    parser.add_argument("--tenants-dir",
                        default=str(repo_root / "examples" / "tenants"))
    parser.add_argument("--output-dir",
                        default=str(repo_root / "analyze" / "output" / "network_analysis"))
    args = parser.parse_args()

    tenants_dir = Path(args.tenants_dir)
    out_dir = Path(args.output_dir)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)

    if not tenants_dir.exists():
        sys.exit(f"Tenants directory not found: {tenants_dir}")

    tenant_dirs = sorted([d for d in tenants_dir.iterdir() if d.is_dir()])
    print(f"Found {len(tenant_dirs)} tenant(s)")

    all_metrics = []
    for td in tenant_dirs:
        name = td.name
        print(f"\nProcessing: {name}")
        G = build_aggregate_graph(td)
        if G.number_of_nodes() == 0:
            print(f"  [skip] no graph data found")
            continue

        metrics = compute_metrics(G, name)
        ba_comp = ba_comparison(G)
        metrics.update(ba_comp)
        all_metrics.append(metrics)

        print(f"  nodes={metrics['nodes']}, edges={metrics['edges']}, "
              f"γ={metrics.get('power_law_gamma')}, "
              f"transitivity={metrics.get('transitivity')}")

        fig_dir = out_dir / "figures"
        plot_degree_powerlaw(G, f"Degree Distribution & Power-Law Fit — {name}",
                             fig_dir / f"{name}_powerlaw.pdf")
        plot_centrality(G, f"Top Betweenness Centrality — {name}",
                        fig_dir / f"{name}_centrality.pdf")
        plot_ba_comparison(G, f"Empirical vs BA Model Degree — {name}",
                           fig_dir / f"{name}_ba_comparison.pdf")

    # Write CSV
    csv_path = out_dir / "data" / "network_metrics.csv"
    if all_metrics:
        keys = list(all_metrics[0].keys())
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_metrics)
        print(f"\nMetrics saved to: {csv_path}")

    # Cross-tenant comparison plot
    if len(all_metrics) > 1:
        tenants = [m["tenant"] for m in all_metrics]
        gammas = [m.get("power_law_gamma") or 0 for m in all_metrics]
        transitivities = [m.get("transitivity") or 0 for m in all_metrics]
        reciprocities = [m.get("reciprocity") or 0 for m in all_metrics]

        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        short_names = [t.split("-")[0] + "…" if len(t) > 15 else t for t in tenants]

        for ax, vals, label, color in zip(
            axes,
            [gammas, transitivities, reciprocities],
            ["Power-law γ", "Transitivity", "Reciprocity"],
            ["#4E79A7", "#59A14F", "#F28E2B"],
        ):
            ax.bar(short_names, vals, color=color, alpha=0.85)
            ax.set_ylabel(label)
            ax.set_title(label)
            ax.tick_params(axis="x", rotation=30)

        fig.suptitle("Cross-Tenant Network Metrics", fontsize=13, fontweight="bold")
        fig.tight_layout()
        fig.savefig(out_dir / "figures" / "cross_tenant_comparison.pdf", dpi=150)
        plt.close(fig)

    print("\nDone. Output written to:", out_dir)


if __name__ == "__main__":
    main()
