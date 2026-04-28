import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ── Aggregate numbers from tab:agent_ranking (experiments_results.tex) ──
agents = ['ReAct-v1 (4o)', 'ReAct-v2 (4o)', 'Researcher (4o-mini)', 'ReAct-v1 (4o-mini)']

agg_assr   = {'ReAct-v1 (4o)': 0.638, 'ReAct-v2 (4o)': 0.564, 'Researcher (4o-mini)': 0.557, 'ReAct-v1 (4o-mini)': 0.589}
agg_rc_rel = {'ReAct-v1 (4o)': 0.551, 'ReAct-v2 (4o)': 0.471, 'Researcher (4o-mini)': 0.649, 'ReAct-v1 (4o-mini)': 0.704}
agg_cite   = {'ReAct-v1 (4o)': 0.675, 'ReAct-v2 (4o)': 0.580, 'Researcher (4o-mini)': 0.711, 'ReAct-v1 (4o-mini)': 0.751}

colors = {
    'ReAct-v1 (4o)':      '#4C72B0',
    'ReAct-v2 (4o)':      '#DD8452',
    'Researcher (4o-mini)': '#C44E52',
    'ReAct-v1 (4o-mini)': '#55A868',
}

fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(11, 4.2))

def auto_ylim(values, pad_frac=0.25, step=0.05):
    """Compute tight y-limits rounded to nearest step with padding."""
    vals = list(values.values())
    lo, hi = min(vals), max(vals)
    span = hi - lo
    pad = max(span * pad_frac, 0.02)  # at least 0.02 padding
    ymin = np.floor((lo - pad) / step) * step
    ymax = np.ceil((hi + pad) / step) * step
    return (max(ymin, 0), ymax)

def make_bar(ax, values, title, ylabel, ylim=None):
    x = np.arange(len(agents))
    vals = [values[a] for a in agents]
    bars = ax.bar(x, vals, width=0.55,
                  color=[colors[a] for a in agents], edgecolor='white', linewidth=0.5)
    # Value labels on bars
    for xi, v in zip(x, vals):
        ax.text(xi, v + (ylim[1] - ylim[0]) * 0.02, f'{v:.3f}',
                ha='center', va='bottom', fontsize=7.5, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(agents, fontsize=8, rotation=25, ha='right')
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight='bold')
    if ylim:
        ax.set_ylim(ylim)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(axis='y', labelsize=8)

ylim1 = auto_ylim(agg_assr)
ylim2 = auto_ylim(agg_rc_rel)
ylim3 = auto_ylim(agg_cite)

make_bar(ax1, agg_assr, 'Assertion Score', 'Score', ylim=ylim1)
make_bar(ax2, agg_rc_rel, 'Response-Citation Relevance', 'Score', ylim=ylim2)
make_bar(ax3, agg_cite, 'Composite Citation Score', 'Score', ylim=ylim3)

fig.tight_layout()
fig.savefig('figures/aggregate_assr_rcrel.pdf', bbox_inches='tight', dpi=300)
fig.savefig('figures/aggregate_assr_rcrel.png', bbox_inches='tight', dpi=200)
print("Saved figures/aggregate_assr_rcrel.pdf and .png")
for a in agents:
    print(f"  {a}: Assr={agg_assr[a]:.3f}, RC-Rel={agg_rc_rel[a]:.3f}, Cite={agg_cite[a]:.3f}")
