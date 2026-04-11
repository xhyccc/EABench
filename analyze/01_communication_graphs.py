"""
01_communication_graphs.py
==========================
Build and visualise directed communication graphs for every EABench tenant.

For each tenant the script:
  * Loads emails, direct-chats, group-chats and meetings from the config YAMLs.
  * Constructs a *per-channel* directed multigraph where nodes are user IDs and
    edges represent individual communication events (with timestamp metadata).
  * Constructs an *aggregate* directed weighted graph (edge weight = number of
    interactions) merging all channels.
  * Saves:
      - figures/  – one PNG per tenant (spring-layout network drawing)
      - data/     – edge-list CSV and graph-level summary CSV

Usage
-----
    python analyze/01_communication_graphs.py \
        --tenants-dir examples/tenants \
        --output-dir  analyze/output/graphs

All paths are relative to the repo root by default.
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import networkx as nx
import numpy as np
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def tenant_name(tenant_dir: Path) -> str:
    return tenant_dir.name


# ---------------------------------------------------------------------------
# Edge extraction
# ---------------------------------------------------------------------------

def edges_from_emails(emails: list, channel: str = "email"):
    """Return list of (src, dst, channel, timestamp) tuples."""
    edges = []
    for msg in emails:
        src = msg.get("from_user", "")
        ts = str(msg.get("timestamp", ""))
        for dst in (msg.get("to_users") or []):
            edges.append((src, dst, channel, ts))
        for dst in (msg.get("cc_users") or []):
            edges.append((src, dst, f"{channel}_cc", ts))
    return edges


def edges_from_chats(chats: list, channel: str = "chat"):
    edges = []
    for conv in chats:
        for msg in (conv.get("messages") or []):
            src = msg.get("from_user", "")
            dst = msg.get("to_user", "")
            ts = str(msg.get("timestamp", ""))
            if src and dst:
                edges.append((src, dst, channel, ts))
    return edges


def edges_from_group_chats(gchats: list, channel: str = "group_chat"):
    edges = []
    for conv in gchats:
        messages = conv.get("messages") or []
        participants = conv.get("participants") or []
        for msg in messages:
            src = msg.get("from_user", "")
            ts = str(msg.get("timestamp", ""))
            # In a group chat every participant is a notional receiver
            for dst in participants:
                if dst != src:
                    edges.append((src, dst, channel, ts))
    return edges


def edges_from_meetings(meetings: list, channel: str = "meeting"):
    edges = []
    for mtg in meetings:
        organizer = mtg.get("organizer", "")
        attendees = mtg.get("attendees") or []
        ts = str(mtg.get("start_time", ""))
        # organizer → every attendee
        for att in attendees:
            if att != organizer:
                edges.append((organizer, att, channel, ts))
        # attendees ↔ attendees (undirected meeting participation)
        for i, a in enumerate(attendees):
            for b in attendees[i + 1:]:
                edges.append((a, b, channel, ts))
                edges.append((b, a, channel, ts))
    return edges


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

CHANNEL_COLOR = {
    "email":       "#4E79A7",
    "email_cc":    "#A0CBE8",
    "chat":        "#F28E2B",
    "group_chat":  "#FFBE7D",
    "meeting":     "#59A14F",
}


def build_graphs(edge_list):
    """Build per-channel and aggregate DiGraph from a flat edge list."""
    per_channel: dict[str, nx.DiGraph] = defaultdict(nx.DiGraph)
    aggregate = nx.DiGraph()

    for src, dst, channel, ts in edge_list:
        if not src or not dst:
            continue

        # per-channel (simple, last-timestamp wins for attr)
        G = per_channel[channel]
        if G.has_edge(src, dst):
            G[src][dst]["count"] += 1
        else:
            G.add_edge(src, dst, count=1, channel=channel, last_ts=ts)

        # aggregate
        base = channel.split("_cc")[0]  # treat cc edges as email
        if aggregate.has_edge(src, dst):
            aggregate[src][dst]["weight"] += 1
            aggregate[src][dst]["channels"].add(base)
        else:
            aggregate.add_edge(src, dst, weight=1, channels={base})

    return dict(per_channel), aggregate


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def draw_aggregate_graph(G: nx.DiGraph, title: str, out_path: Path):
    if len(G.nodes) == 0:
        return

    fig, ax = plt.subplots(figsize=(14, 10))

    pos = nx.spring_layout(G, seed=42, k=2.5 / max(1, np.sqrt(len(G.nodes))))

    # Node sizes proportional to in-degree
    in_deg = dict(G.in_degree())
    node_sizes = [300 + 400 * in_deg.get(n, 0) for n in G.nodes]

    # Edge widths / colours (aggregate graph uses "weight"; per-channel uses "count")
    weights = [G[u][v].get("weight", G[u][v].get("count", 1)) for u, v in G.edges()]
    max_w = max(weights) if weights else 1
    widths = [0.5 + 3.0 * w / max_w for w in weights]

    # Decide edge colours by most-used channel set
    def edge_colour(u, v):
        chs = G[u][v].get("channels", set())
        priority = ["email", "chat", "group_chat", "meeting"]
        for ch in priority:
            if ch in chs:
                return CHANNEL_COLOR.get(ch, "#999999")
        return "#999999"

    edge_colors = [edge_colour(u, v) for u, v in G.edges()]

    nx.draw_networkx_nodes(G, pos, node_size=node_sizes,
                           node_color="#2196F3", alpha=0.85, ax=ax)
    nx.draw_networkx_labels(G, pos, font_size=7, ax=ax)
    nx.draw_networkx_edges(G, pos, width=widths, edge_color=edge_colors,
                           arrows=True, arrowsize=12,
                           connectionstyle="arc3,rad=0.1", ax=ax)

    # Legend
    legend_patches = [
        plt.Line2D([0], [0], color=c, lw=2, label=ch.replace("_", " "))
        for ch, c in CHANNEL_COLOR.items()
    ]
    ax.legend(handles=legend_patches, loc="lower left", fontsize=8)

    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def draw_degree_distribution(G: nx.DiGraph, title: str, out_path: Path):
    if len(G.nodes) == 0:
        return
    in_degs = sorted([d for _, d in G.in_degree()], reverse=True)
    out_degs = sorted([d for _, d in G.out_degree()], reverse=True)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, degs, label in zip(axes,
                                [in_degs, out_degs],
                                ["In-degree", "Out-degree"]):
        unique, counts = np.unique(degs, return_counts=True)
        ax.bar(unique, counts, color="#4E79A7", alpha=0.8)
        ax.set_xlabel(label)
        ax.set_ylabel("Count")
        ax.set_title(f"{label} distribution")

    fig.suptitle(title, fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def graph_stats(G: nx.DiGraph, tenant: str, channel: str) -> dict:
    n = G.number_of_nodes()
    e = G.number_of_edges()
    if n == 0:
        return {"tenant": tenant, "channel": channel,
                "nodes": 0, "edges": 0}
    density = nx.density(G)

    # Weakly connected giant component
    wcc = max(nx.weakly_connected_components(G), key=len) if n > 1 else set(G.nodes)
    G_wcc = G.subgraph(wcc).copy()

    avg_in = np.mean([d for _, d in G.in_degree()]) if n > 0 else 0
    avg_out = np.mean([d for _, d in G.out_degree()]) if n > 0 else 0

    # Reciprocity
    recip = nx.reciprocity(G) if e > 0 else 0.0

    # Betweenness centrality (top node)
    bc = nx.betweenness_centrality(G_wcc, normalized=True)
    top_bc_node = max(bc, key=bc.get) if bc else ""
    top_bc_val = bc.get(top_bc_node, 0.0)

    return {
        "tenant": tenant,
        "channel": channel,
        "nodes": n,
        "edges": e,
        "density": round(density, 4),
        "avg_in_degree": round(avg_in, 2),
        "avg_out_degree": round(avg_out, 2),
        "reciprocity": round(recip, 4),
        "top_betweenness_node": top_bc_node,
        "top_betweenness_value": round(top_bc_val, 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_tenant(tenant_dir: Path, out_dir: Path):
    name = tenant_name(tenant_dir)
    cfg = tenant_dir / "config"
    if not cfg.exists():
        return None

    # Load communication data
    emails     = load_yaml(cfg / "emails.yaml")     if (cfg / "emails.yaml").exists()     else []
    chats      = load_yaml(cfg / "chats.yaml")      if (cfg / "chats.yaml").exists()      else []
    gchats     = load_yaml(cfg / "group_chats.yaml")if (cfg / "group_chats.yaml").exists()else []
    meetings   = load_yaml(cfg / "meetings.yaml")   if (cfg / "meetings.yaml").exists()   else []

    edge_list = (
        edges_from_emails(emails)
        + edges_from_chats(chats)
        + edges_from_group_chats(gchats)
        + edges_from_meetings(meetings)
    )

    per_channel, aggregate = build_graphs(edge_list)

    # Output paths
    fig_dir = out_dir / "figures"
    data_dir = out_dir / "data"
    fig_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Draw aggregate graph
    draw_aggregate_graph(
        aggregate,
        title=f"Communication Network — {name}",
        out_path=fig_dir / f"{name}_aggregate_network.png",
    )
    draw_degree_distribution(
        aggregate,
        title=f"Degree Distribution (aggregate) — {name}",
        out_path=fig_dir / f"{name}_degree_dist.png",
    )

    # Per-channel graphs
    for ch, G in per_channel.items():
        draw_aggregate_graph(
            G,
            title=f"{ch.replace('_',' ').title()} Network — {name}",
            out_path=fig_dir / f"{name}_{ch}_network.png",
        )

    # Edge-list CSV
    with open(data_dir / f"{name}_edgelist.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["source", "target", "channel", "timestamp"])
        for src, dst, ch, ts in edge_list:
            writer.writerow([src, dst, ch, ts])

    # Summary stats
    stats = []
    for ch, G in per_channel.items():
        stats.append(graph_stats(G, name, ch))
    stats.append(graph_stats(aggregate, name, "aggregate"))

    print(f"  [{name}] nodes={aggregate.number_of_nodes()}, "
          f"edges={aggregate.number_of_edges()}, "
          f"channels={list(per_channel.keys())}")
    return stats


def main():
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(description="Build communication graphs for EABench tenants.")
    parser.add_argument("--tenants-dir", default=str(repo_root / "examples" / "tenants"),
                        help="Directory containing tenant sub-directories.")
    parser.add_argument("--output-dir", default=str(repo_root / "analyze" / "output" / "graphs"),
                        help="Where to save figures and data.")
    args = parser.parse_args()

    tenants_dir = Path(args.tenants_dir)
    out_dir = Path(args.output_dir)

    if not tenants_dir.exists():
        sys.exit(f"Tenants directory not found: {tenants_dir}")

    tenant_dirs = sorted([d for d in tenants_dir.iterdir() if d.is_dir()])
    print(f"Found {len(tenant_dirs)} tenant(s): {[d.name for d in tenant_dirs]}")

    all_stats = []
    for td in tenant_dirs:
        print(f"\nProcessing: {td.name}")
        stats = process_tenant(td, out_dir)
        if stats:
            all_stats.extend(stats)

    # Write global summary CSV
    summary_path = out_dir / "data" / "graph_summary.csv"
    if all_stats:
        keys = list(all_stats[0].keys())
        with open(summary_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_stats)
        print(f"\nGraph summary saved to: {summary_path}")

    print("\nDone. Output written to:", out_dir)


if __name__ == "__main__":
    main()
