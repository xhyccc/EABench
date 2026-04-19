#!/usr/bin/env python3
"""Generate tool-usage breakdown and browsing-ablation plots for the paper."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ── Aggregate tool usage (mean calls/case across all 525 cases per agent) ──
# Computed from eval JSONs; chat includes search_chat + search_group_chat + search_channel
agents = ['ReAct-v1', 'ReAct-v2', 'ReAct-v3', 'Researcher', 'Retrieval']
tools  = ['search_email', 'search_chat', 'search_meeting', 'search_file',
          'search_people', 'read_file', 'search_in_file']
tool_labels = ['Email', 'Chat', 'Meeting', 'File', 'People', 'Read', 'Search-in']

data = {  # agent → tool → mean calls/case
    'ReAct-v1':   [0.81, 0.05, 0.17, 0.19, 0.18, 0.27, 0.01],
    'ReAct-v2':   [0.81, 0.06, 0.17, 0.18, 0.16, 0.17, 0.01],
    'ReAct-v3':   [0.62, 0.04, 0.20, 0.30, 0.05, 0.02, 0.00],
    'Researcher': [0.96, 0.34, 0.56, 0.39, 0.87, 0.97, 0.03],
    'Retrieval':  [0.96, 0.01, 0.03, 0.00, 0.00, 0.00, 0.00],
}

tool_colors = {
    'search_email':   '#4C72B0',
    'search_chat':    '#DD8452',
    'search_meeting': '#55A868',
    'search_file':    '#C44E52',
    'search_people':  '#8172B3',
    'read_file':      '#937860',
    'search_in_file': '#DA8BC3',
}

# ── Panel 1: Stacked horizontal bar — tool breakdown per agent ──
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.5),
                                gridspec_kw={'width_ratios': [1.3, 1]})

y = np.arange(len(agents))
lefts = np.zeros(len(agents))
for i, (tool, label) in enumerate(zip(tools, tool_labels)):
    vals = [data[a][i] for a in agents]
    bars = ax1.barh(y, vals, left=lefts, height=0.6,
                    color=tool_colors[tool], edgecolor='white', linewidth=0.5,
                    label=label)
    lefts += vals

ax1.set_yticks(y)
ax1.set_yticklabels(agents, fontsize=9)
ax1.set_xlabel('Mean Tool Calls per Case', fontsize=10)
ax1.set_title('Tool Usage Breakdown', fontsize=11, fontweight='bold')
ax1.legend(loc='lower right', fontsize=7, ncol=2, frameon=False)
ax1.spines['top'].set_visible(False)
ax1.spines['right'].set_visible(False)
ax1.invert_yaxis()

# ── Panel 2: Grouped bars — browsing ablation (pass rate) ──
# Per-tenant pass rates from tab:tool_ablation
tenants = ['Bertrand', 'Cambford', 'ZAI']
ablation_agents = ['Retrieval', 'ReAct-v3', 'Researcher']
ablation_colors = {
    'Retrieval':  '#999999',
    'ReAct-v3':   '#55A868',
    'Researcher': '#C44E52',
}
pass_rates = {
    'Retrieval':  [0.302, 0.222, 0.209],
    'ReAct-v3':   [0.395, 0.296, 0.363],
    'Researcher': [0.432, 0.346, 0.289],
}

x = np.arange(len(tenants))
width = 0.22
for i, agent in enumerate(ablation_agents):
    offset = (i - 1) * width
    bars = ax2.bar(x + offset, pass_rates[agent], width,
                   color=ablation_colors[agent], edgecolor='white', linewidth=0.5,
                   label=agent)

ax2.set_xticks(x)
ax2.set_xticklabels(tenants, fontsize=9)
ax2.set_ylabel('Pass Rate', fontsize=10)
ax2.set_ylim(0, 0.55)
ax2.set_title('Snippet-Only vs. Browsing', fontsize=11, fontweight='bold')
ax2.legend(fontsize=8, frameon=False)
ax2.spines['top'].set_visible(False)
ax2.spines['right'].set_visible(False)

fig.tight_layout()
fig.savefig('figures/tool_ablation_combined.pdf', bbox_inches='tight', dpi=300)
fig.savefig('figures/tool_ablation_combined.png', bbox_inches='tight', dpi=200)
print("Saved figures/tool_ablation_combined.pdf and .png")
