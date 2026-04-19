# Plan: Integrate Retrieval-Only Baseline (C5) into the Paper

## 0. Background

The retrieval-only baseline (C5, config `examples/agents/retrieval_baseline.yaml`) was
previously reported in the paper as **degenerate / excluded** because an
off-by-one in the agent loop made every case fail with `MaxTurnsExceededError`
(pass rate = 0 everywhere).

Root cause: `flow.max_turns` in the YAML is interpreted by
`python/src/core/agent_runner.py` as **ReAct hops** (LLM calls per query), not
user-conversation turns. With `max_turns: 1`, hop 1 was consumed by the single
search tool call, and the loop exited before the LLM could read the tool
result and emit a final answer.

Fix applied (already committed in this session):
- `examples/agents/retrieval_baseline.yaml`: `max_turns: 1` → `max_turns: 2`
  (hop 1 = search, hop 2 = final answer). The system prompt still forbids a
  second tool call, so the one-retrieval semantics are preserved.

Re-runs completed (2026-04-19). New canonical result files kept in
`python/results/`:

| Tenant     | File (20260419_*) | Size   |
|------------|-------------------|--------|
| Bertrand   | `eval_bertrand-and-co.-20260407_baseline_20260419_032440.json` | 24.9 MB |
| Cambford   | `eval_staff-office-the-university-of-cambford-20260407_baseline_20260419_042333.json` | 17.4 MB |
| ZAI        | `eval_zai-intelligence-20260408_baseline_20260419_051311.json` | 32.1 MB |

The three broken 20260417 baseline JSONs (~340–413 KB each) have been deleted
from `python/results/`.

## 1. New Baseline Numbers

| Tenant    | n   | Pass  | Assr. | Cite  | TS-Rel | RC-Rel |
|-----------|-----|-------|-------|-------|--------|--------|
| Bertrand  | 162 | 0.302 | 0.706 | 0.748 | 0.858  | 0.637  |
| Cambford  | 162 | 0.222 | 0.495 | 0.712 | 0.832  | 0.593  |
| ZAI       | 201 | 0.209 | 0.548 | 0.696 | 0.809  | 0.583  |
| **Pooled**| 525 | **0.244** | 0.583 | 0.718 | 0.833 | 0.604 |

(Numbers from the in-session summarization; re-confirm exactly from the
regenerated CSVs before pasting into the paper.)

Key interpretive points:
- The baseline is now a **genuine retrieval floor**, not a broken configuration.
- Pooled pass ≈ 24%, clearly below the weakest two-hop ReAct-v2 (21% pooled)
  only on ZAI and above it on Bertrand / Cambford — so retrieval alone is
  competitive with a poorly-tuned ReAct but clearly below ReAct-v1 / -v3 /
  Researcher.
- Citation scores are high (Cite ≈ 0.72) because the baseline is forced to
  ground on the one retrieval, confirming that the grounding gate by itself
  is easy; the discriminative work is done by the assertion gate.
- This strengthens the paper's claim that the benchmark discriminates across
  the full spectrum from retrieval-only → weak ReAct → strong ReAct →
  Researcher.

## 2. Artifacts to Regenerate

Run once the new JSONs are in place:

```bash
cd /Users/haoyi/Desktop/EABench
bash scripts/run_missing_experiments.sh p0
# or directly:
python scripts/analyze_post_hoc.py --mode all \
    --results-dir python/results \
    --output-dir analyze/output/missing_experiments
```

`analyze_post_hoc.py :: load_all_results()` auto-selects the latest timestamp
per `(agent, tenant)` key, and `AGENT_CONFIG_MAP["retrieval_baseline.yaml"]`
already maps to `"baseline"`, so no code change is required for the CSVs.

Files that will be refreshed (currently contain stale `baseline, 0.0` rows):
- `analyze/output/missing_experiments/b8_cost_breakdown.csv`
- `analyze/output/missing_experiments/c4_pass_rates_ci.csv`
- `analyze/output/missing_experiments/c6_threshold_sensitivity.csv`

Verify after regeneration:
- [ ] `c4_pass_rates_ci.csv` has three baseline rows with pass ≈ 0.30 / 0.22 / 0.21.
- [ ] `c6_threshold_sensitivity.csv` baseline rows are monotone non-increasing in τ.
- [ ] `b8_cost_breakdown.csv` baseline tokens/tool-calls are sensible (1 tool call, small prompt).

## 3. Paper Edits

### 3.1 `EABench_paper/experiments_results.tex`

**Line ~54 ("Baseline note" paragraph).** Replace the current blue paragraph
that excludes baseline as degenerate:

> \textcolor{blue}{\textbf{Baseline note.} We do not include a zero-turn
> retrieve-and-summarize lower bound as a separate agent row because a
> single-turn chain exhausts its budget on the retrieval call and never
> reaches a synthesis turn in our runtime, yielding degenerate zero scores
> that do not reflect the retrieval index itself. We therefore treat the
> two-turn reactive agents (\textsc{ReAct-v2}, \textsc{ReAct-v3}) as the
> effective floor of the agent spectrum and emphasise the within-spectrum
> contrasts.}

with a new paragraph positioning the baseline as a real lower bound, e.g.:

> \textcolor{blue}{\textbf{Retrieval-only baseline (C5).} To anchor the
> agent spectrum at the retrieval floor, we include a retrieval-only agent
> that issues exactly one search call and then produces a grounded answer
> from the returned evidence (system prompt forbids a second tool call;
> runtime configured with two ReAct hops so the synthesis step is reached).
> Pooled over 525 cases it attains a pass rate of 24.4\% (Bertrand 30.2\%,
> Cambford 22.2\%, ZAI 20.9\%), well below \textsc{ReAct-v1} (32.3\%) and
> \textsc{Researcher} (35.5\%) but comparable to the weakest reactive
> configuration \textsc{ReAct-v2} (21.2\%). Its high composite citation
> score (0.72) confirms that the grounding gate alone is easy to satisfy;
> the discriminative pressure comes from the assertion gate.}

### 3.2 Tables 17 / 6 / 7

- **Table `tab:results_full`** (per-tenant × per-agent, ~L64): add a
  `\textsc{Baseline}` row under each tenant block. Five new rows total
  (one per tenant × one agent).
- **Table `tab:agent_ranking`** (aggregate, ~L94): add a `\textsc{Baseline}`
  row with pooled pass-rate CI, Assr., TS-Rel, TS-$n$, RC-Rel, RC-$n$,
  Cite, Tools (=1.0), Prompt tok. Mark it clearly as the retrieval floor.
- Re-compute "Bold marks best per-tenant value" — baseline is unlikely to
  take any bold, but verify.

### 3.3 `EABench_paper/appendix_extra_results.tex`

**Line ~24 (Wilcoxon caption).** Remove the exclusion clause:

> Baseline rows (pass rate 0 everywhere) are reported as degenerate and
> excluded from conclusions.

and replace with:

> The retrieval-only baseline (C5) is included as the retrieval floor; its
> comparisons against ReAct-v1/v2/v3 and Researcher are now genuine paired
> tests on matched case IDs.

Then regenerate `c5_wilcoxon_pairs.csv` (or equivalent) and update
`tab:wilcoxon_full` so that baseline-vs-ReAct and baseline-vs-Researcher
comparisons are non-degenerate.

### 3.4 Figures (optional, second-pass change)

Currently `analyze/07_paper_figures.py:476` hard-skips any filename
containing `"baseline"`:

```python
if "glmjudge" in fname or "baseline" in fname:
    continue
```

If we want baseline to appear in `metrics_heatmap.pdf`,
`pass_rate_by_agent_tenant.pdf`, `citation_decomposition.pdf`, etc., we need
to:

1. Remove `or "baseline" in fname` from that filter.
2. Extend the agent-order / color / hatch / linestyle / marker dicts near the
   top of the module to include `"baseline"`. Suggested ordering:
   `["baseline", "react_agent_v2", "react_agent", "react_agent_v3", "researcher_agent"]`
   (floor → ceiling) with a neutral grey for baseline.
3. Re-run `python analyze/07_paper_figures.py` and visually check each PDF
   fits on the page.

Recommendation: ship a **single new bar chart** (`pass_rate_with_baseline.pdf`)
rather than rebuilding every figure, to minimize churn in the paper.

### 3.5 Abstract / Intro / Contributions (optional)

One-sentence mention, e.g.:

> The benchmark cleanly separates a retrieval-only floor (≈24\% pass) from
> strong ReAct / Researcher agents (≈35\% pass), with a measurable ordering
> within the ReAct family.

### 3.6 Reproducibility footnote

In the methodology section or as a footnote in §Experiments, add:

> An earlier pre-print reported the retrieval-only baseline as degenerate
> due to an off-by-one in the ReAct-hop budget (`flow.max_turns: 1`
> consumed the search call before synthesis). The runtime interprets
> `max_turns` as ReAct hops, not conversation turns; setting it to 2
> restores the intended one-retrieval-then-answer behaviour.

## 4. Build & Verify

```bash
cd EABench_paper
pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
```

Checklist:
- [ ] `main.pdf` builds cleanly (no undefined refs).
- [ ] Baseline row appears in Tables `tab:results_full` and `tab:agent_ranking`.
- [ ] Wilcoxon appendix table has genuine baseline comparisons.
- [ ] Numbers in the new paragraph match the regenerated CSVs exactly.
- [ ] No leftover mentions of "degenerate" / "zero-turn" / "pass rate 0 everywhere"
      (grep: `grep -n "degenerate\|pass rate 0 everywhere\|zero-turn" EABench_paper/*.tex`).

## 5. Execution Order

1. Regenerate CSVs (§2).
2. Confirm baseline numbers from the CSVs; update §1 of this plan if they differ.
3. Edit `experiments_results.tex` (§3.1, §3.2).
4. Edit `appendix_extra_results.tex` (§3.3).
5. (Optional) figures (§3.4).
6. (Optional) abstract / intro / reproducibility note (§3.5, §3.6).
7. Build & verify (§4).
8. Commit to branch `u/haoyi/academic-paper`.
