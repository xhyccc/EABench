# EABench — Analysis Scripts

This directory contains four standalone Python scripts for analysing EABench
tenant communication data and evaluation results.

## Quick start

```bash
# From the repo root:
pip install networkx matplotlib scipy numpy pandas seaborn

python analyze/01_communication_graphs.py
python analyze/02_network_analysis.py
python analyze/03_inter_event_times.py
python analyze/04_eval_analysis.py
```

All scripts write their output under `analyze/output/` (created automatically).

---

## Script overview

### `01_communication_graphs.py` — Communication Graph Visualisation

Builds a directed communication graph for each tenant from all four channel
types (emails, direct chats, group chats, meetings) and visualises them.

**What it produces**

| Output | Description |
|--------|-------------|
| `output/graphs/figures/<tenant>_aggregate_network.pdf` | Spring-layout directed graph, all channels merged; edge colour = dominant channel; node size ∝ in-degree |
| `output/graphs/figures/<tenant>_degree_dist.pdf` | In/out-degree distribution bar charts |
| `output/graphs/figures/<tenant>_<channel>_network.pdf` | Per-channel network (email, chat, group\_chat, meeting) |
| `output/graphs/data/<tenant>_edgelist.csv` | Flat edge list: `source, target, channel, timestamp` |
| `output/graphs/data/graph_summary.csv` | Node/edge count, density, reciprocity, top betweenness node per (tenant × channel) |

**Usage**

```bash
python analyze/01_communication_graphs.py \
    --tenants-dir examples/tenants \
    --output-dir  analyze/output/graphs
```

---

### `02_network_analysis.py` — Complex-Network & Barabási–Albert Analysis

Applies tools from complex-network theory to the aggregate communication graph
of each tenant, with a focus on Barabási–Albert (BA) preferential-attachment
signatures.

**Metrics computed**

| Metric | Notes |
|--------|-------|
| Power-law exponent **γ** | Fit to CCDF of in-degree via OLS log-log regression; BA networks yield γ ≈ 3; human communication networks typically γ ∈ [2, 3] |
| Transitivity (global clustering coefficient) | High → dense triangles; consistent with real org networks |
| Reciprocity | Fraction of edges that are bidirectional |
| Diameter & avg shortest path | Computed on the undirected giant weakly-connected component |
| Betweenness centrality | Top-3 nodes (brokers / information hubs) |
| BA comparison | Generates a synthetic BA graph of the same size and overlays degree sequences |

**What it produces**

| Output | Description |
|--------|-------------|
| `output/network_analysis/figures/<tenant>_powerlaw.pdf` | Linear + log-log CCDF with power-law fit |
| `output/network_analysis/figures/<tenant>_centrality.pdf` | Top-15 betweenness centrality bar chart |
| `output/network_analysis/figures/<tenant>_ba_comparison.pdf` | Rank-ordered degree: empirical vs BA synthetic |
| `output/network_analysis/figures/cross_tenant_comparison.pdf` | γ, transitivity, reciprocity across tenants |
| `output/network_analysis/data/network_metrics.csv` | All metrics in a single table |

**Usage**

```bash
python analyze/02_network_analysis.py \
    --tenants-dir examples/tenants \
    --output-dir  analyze/output/network_analysis
```

---

### `03_inter_event_times.py` — Inter-Event Time Analysis

Reproduces Barabási et al.'s human-dynamics analysis for EABench
communication data.  The key finding in that literature is that
human communication is **bursty**: inter-event times (IETs) follow
heavy-tail distributions rather than Poisson processes.

**Metrics computed per (tenant × channel)**

| Metric | Formula / Notes |
|--------|-----------------|
| **Burstiness B** | `(σ − μ) / (σ + μ)` ∈ [−1, +1]; B > 0 → bursty, B ≈ 0 → Poisson, B < 0 → regular periodic |
| **Memory M** | Pearson correlation between consecutive IETs; M > 0 → clustered bursts |
| Power-law exponent **α** | Fit to CCDF of IETs; `P(τ ≥ t) ~ t^(−α)`; heavy tail if α ≲ 2 |
| Log-normal fit | μ, σ of `log τ`; goodness-of-fit via KS test |

**Key findings from the data**

- **Chat & group-chat** channels are highly bursty (B ≈ 0.6–0.7) with low
  power-law exponents (α ≈ 0.3–0.4), consistent with real-world instant
  messaging data reported by Barabási et al.
- **Email** is closer to Poisson / slightly bursty (B ≈ −0.05 to +0.17, α ≈ 1.3–2.0).
- **Meeting** invitations show near-zero burstiness and a moderate positive
  memory coefficient, reflecting scheduled patterns.

**What it produces**

| Output | Description |
|--------|-------------|
| `output/inter_event_times/figures/<tenant>_iet_ccdf.pdf` | Multi-channel IET CCDF (log-log) with power-law overlays |
| `output/inter_event_times/figures/<tenant>_<channel>_iet_hist.pdf` | Histogram (linear + log scale) with log-normal fit |
| `output/inter_event_times/figures/burstiness_heatmap.pdf` | Heatmap of B across all (tenant × channel) combinations |
| `output/inter_event_times/figures/burstiness_memory_overview.pdf` | Scatter: B and M per tenant per channel |
| `output/inter_event_times/data/<tenant>_iets.csv` | Per-sender IET records |
| `output/inter_event_times/data/iet_summary.csv` | All metrics in one table |

**Usage**

```bash
python analyze/03_inter_event_times.py \
    --tenants-dir examples/tenants \
    --output-dir  analyze/output/inter_event_times
```

---

### `04_eval_analysis.py` — Evaluation Result Analysis

Loads all JSON result files from `python/results/` and analyses how agent
configuration affects benchmark performance.

**Two research questions**

1. **Search relevance** — how well does each agent retrieve relevant documents
   (tool search relevance) and how well does it cite them in its final response
   (response citation relevance)?
2. **Assertion pass rates** — what fraction of test-case assertions does each
   agent satisfy, and does better retrieval translate to higher pass rates?

**Agent configurations evaluated**

| Agent ID | Model | Temperature | Notes |
|----------|-------|-------------|-------|
| `react_agent` | gpt-4o | 0.7 | Baseline ReAct loop |
| `react_agent_v2` | gpt-4o | 0.5 | Revised prompt, lower temp |
| `researcher_agent` | gpt-4o-mini | 0.0 | Planning-first, greedy |

**Key findings from current results**

| Agent | Pass Rate | Assertion Score | Tool Search Relevance | Response Citation Relevance |
|-------|-----------|-----------------|----------------------|-----------------------------|
| `researcher_agent` | **0.355** | 0.557 | 0.773 | **0.649** |
| `react_agent` | 0.323 | **0.638** | **0.799** | 0.551 |
| `react_agent_v2` | 0.212 | 0.564 | 0.689 | 0.471 |

- `react_agent` retrieves the most relevant tool results but does not always
  convert them into correct responses (assertion gap).
- `researcher_agent` (planning-based) achieves the highest overall pass rate
  despite lower tool search relevance — suggesting the planning step compensates
  for retrieval precision.
- `react_agent_v2` under-performs on all metrics, likely due to the tighter
  temperature combined with prompt changes that constrain tool-call diversity.

**What it produces**

| Output | Description |
|--------|-------------|
| `output/eval_analysis/figures/agent_radar.pdf` | Radar chart comparing agents on 5 key metrics |
| `output/eval_analysis/figures/metrics_heatmap.pdf` | Heatmap: metric × (tenant, agent) |
| `output/eval_analysis/figures/pass_rate_by_agent_tenant.pdf` | Grouped bar chart per tenant |
| `output/eval_analysis/figures/scatter_relevance_vs_assertion.pdf` | Tool relevance vs assertion score per case |
| `output/eval_analysis/figures/correlation_matrix.pdf` | Pearson correlations among all case-level metrics |
| `output/eval_analysis/figures/latency_boxplot.pdf` | Case latency distribution per agent |
| `output/eval_analysis/figures/<tenant>_pass_rate.pdf` | Per-tenant pass-rate bar chart |
| `output/eval_analysis/data/agent_ranking.csv` | Global agent ranking table |
| `output/eval_analysis/data/eval_summary.csv` | One row per result file |
| `output/eval_analysis/data/cases.csv` | One row per test case |

**Usage**

```bash
python analyze/04_eval_analysis.py \
    --results-dir python/results \
    --output-dir  analyze/output/eval_analysis
```

---

## Output directory structure

```
analyze/output/
├── graphs/
│   ├── data/
│   │   ├── graph_summary.csv
│   │   └── <tenant>_edgelist.csv
│   └── figures/
│       ├── <tenant>_aggregate_network.pdf
│       ├── <tenant>_degree_dist.pdf
│       └── <tenant>_<channel>_network.pdf
├── network_analysis/
│   ├── data/
│   │   └── network_metrics.csv
│   └── figures/
│       ├── <tenant>_powerlaw.pdf
│       ├── <tenant>_centrality.pdf
│       ├── <tenant>_ba_comparison.pdf
│       └── cross_tenant_comparison.pdf
├── inter_event_times/
│   ├── data/
│   │   ├── iet_summary.csv
│   │   └── <tenant>_iets.csv
│   └── figures/
│       ├── <tenant>_iet_ccdf.pdf
│       ├── <tenant>_<channel>_iet_hist.pdf
│       ├── burstiness_heatmap.pdf
│       └── burstiness_memory_overview.pdf
└── eval_analysis/
    ├── data/
    │   ├── agent_ranking.csv
    │   ├── eval_summary.csv
    │   └── cases.csv
    └── figures/
        ├── agent_radar.pdf
        ├── metrics_heatmap.pdf
        ├── pass_rate_by_agent_tenant.pdf
        ├── assertion_score_by_agent_tenant.pdf
        ├── tool_search_relevance_by_agent_tenant.pdf
        ├── response_citation_relevance_by_agent_tenant.pdf
        ├── pass_fail_breakdown.pdf
        ├── scatter_relevance_vs_assertion.pdf
        ├── correlation_matrix.pdf
        ├── latency_boxplot.pdf
        └── <tenant>_pass_rate.pdf
```

## Dependencies

```
networkx>=3.0
matplotlib>=3.7
scipy>=1.10
numpy>=1.24
pandas>=2.0
seaborn>=0.12
PyYAML>=6.0   (already in EABench requirements)
```
