import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ── Aggregate numbers from tab:agent_ranking (experiments_results.tex) ──
agents = ['ReAct-v1', 'ReAct-v2', 'ReAct-v3', 'Researcher']

agg_assr   = {'ReAct-v1': 0.638, 'ReAct-v2': 0.564, 'ReAct-v3': 0.589, 'Researcher': 0.557}
agg_rc_rel = {'ReAct-v1': 0.551, 'ReAct-v2': 0.471, 'ReAct-v3': 0.704, 'Researcher': 0.649}
agg_cite   = {'ReAct-v1': 0.675, 'ReAct-v2': 0.580, 'ReAct-v3': 0.751, 'Researcher': 0.711}

colors = {
    'ReAct-v1':   '#4C72B0',
    'ReAct-v2':   '#DD8452',
    'ReAct-v3':   '#55A868',
    'Researcher': '#C44E52',
}

fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(10, 3.8))

def make_bar(ax, values, title, ylabel, ylim=None):
    x = np.arange(len(agents))
    bars = ax.bar(x, [values[a] for a in agents], width=0.55,
                  color=[colors[a] for a in agents], edgecolor='white', linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(agents, fontsize=9, rotation=15, ha='right')
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight='bold')
    if ylim:
        ax.set_ylim(ylim)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(axis='y', labelsize=8)

make_bar(ax1, agg_assr, 'Assertion Score', 'Score', ylim=(0, 0.8))
make_bar(ax2, agg_rc_rel, 'Response-Citation Relevance', 'Score', ylim=(0, 0.8))
make_bar(ax3, agg_cite, 'Composite Citation Score', 'Score', ylim=(0, 0.8))

fig.tight_layout()
fig.savefig('figures/aggregate_assr_rcrel.pdf', bbox_inches='tight', dpi=300)
fig.savefig('figures/aggregate_assr_rcrel.png', bbox_inches='tight', dpi=200)
print("Saved figures/aggregate_assr_rcrel.pdf and .png")
for a in agents:
    print(f"  {a}: Assr={agg_assr[a]:.3f}, RC-Rel={agg_rc_rel[a]:.3f}, Cite={agg_cite[a]:.3f}")
