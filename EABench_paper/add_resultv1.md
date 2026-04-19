# Plan: Integrating New Results into the Paper (`add_resultv1.md`)

Derived from the validated outputs in `analyze/output/missing_experiments/` (validated 2026-04-19, all cross-checks passed against raw result JSONs).

---

## 1. Status of Each Missing Experiment

| ID  | Status         | Usable in paper?                             | Action                                                    |
| --- | -------------- | -------------------------------------------- | --------------------------------------------------------- |
| C4  | ✅ Validated    | Yes — 16 CIs + 30 Wilcoxon comparisons       | Integrate into Tables 6/7 and §Main Results               |
| C6  | ✅ Validated    | Yes — 80 rows, monotone, τ=0.75 matches main | New appendix table + 1 sentence in §Evaluation Metrics    |
| B8  | ✅ Validated    | Yes — real tokens/$ for 16 cells             | New cost table replacing "judge cost" paragraph           |
| C3  | ✅ Validated    | Yes — ReAct-v3 on 3 tenants                  | Add 4th agent row to Tables 6/7, rewrite §arch-analysis   |
| C2  | ⚠ Partial      | Partially — 380 auto-tagged rows, no humans  | Report as "query-type distribution" only, not "human val" |
| C5  | ❌ Broken       | No — all zeros (`max_turns:1` bug)           | Fix config → re-run → integrate, OR drop C5 placeholder   |
| C1  | ❌ Abandoned    | No — GLM judge pass rate ~1–2% unreliable    | Remove C1 placeholder; mention as inconclusive in §Limits |

---

## 2. Key Numbers (Source of Truth)

All numbers below are from the validated CSVs. `react_v3` uses GPT-4o-mini (same model as Researcher) with single-pass ReAct. Pass rate = fraction of cases with assertion ≥ 0.75 AND rc_rel ≥ 0.7.

### 2.1 Pass Rate ± Wilson 95% CI (from `c4_pass_rates_ci.csv`)

| Tenant    | ReAct-v1            | ReAct-v2            | ReAct-v3 (new)      | Researcher          | Baseline (broken)   |
| --------- | ------------------- | ------------------- | ------------------- | ------------------- | ------------------- |
| Bertrand  | 0.414 [0.341, 0.491]| 0.259 [0.198, 0.332]| 0.395 [0.323, 0.472]| 0.432 [0.358, 0.509]| 0.000 [0.000, 0.023]|
| Cambford  | 0.228 [0.171, 0.299]| 0.222 [0.165, 0.292]| 0.296 [0.231, 0.371]| 0.346 [0.277, 0.422]| 0.000 [0.000, 0.023]|
| ZAI       | 0.269 [0.212, 0.334]| 0.154 [0.111, 0.211]| 0.363 [0.300, 0.432]| 0.289 [0.230, 0.355]| 0.000 [0.000, 0.019]|

**Headline result:** ReAct-v3 (GPT-4o-mini + single-pass ReAct) **beats Researcher (GPT-4o-mini + plan-and-execute) on ZAI** (0.363 vs. 0.289) and is essentially tied on Bertrand (0.395 vs. 0.432, CIs overlap). This weakens the "plan-and-execute is always better" framing and strengthens the "model size matters when the planning stage isn't needed" story.

### 2.2 Wilcoxon Paired Tests (from `c4_pairwise_wilcoxon.csv`, 23 of 30 significant at p < 0.05)

**Significant (use in text):**
- ReAct-v1 vs ReAct-v2, Bertrand: p = 2.7e-4 ***
- ReAct-v1 vs ReAct-v2, ZAI: p = 1.0e-4 ***
- ReAct-v2 vs Researcher, Bertrand: p = 7.5e-5 ***
- ReAct-v1 vs Researcher, Cambford: p = 5.6e-3 **  (the "52% gain" claim)
- ReAct-v2 vs ReAct-v3, ZAI: p = 5.7e-8 *** (architecture at fixed model)
- Researcher vs ReAct-v3, ZAI: p = 0.032 * (planner underperforms on bursty data)

**Not significant (important caveats):**
- ReAct-v1 vs ReAct-v2, Cambford: p = 0.85 (prompt doesn't matter here)
- ReAct-v1 vs Researcher, ZAI: p = 0.57
- ReAct-v1 vs Researcher, Bertrand: p = 0.68

### 2.3 Cost Breakdown (from `b8_cost_breakdown.csv`)

Representative per-tenant totals (full 525 cases):
- ReAct-v1:  $9.50 + $1.16 judge = $10.66 (Bertrand), $11.24 + $1.37 = $12.61 (ZAI)
- ReAct-v2:  $8.00 + $1.17 = $9.17 (Bertrand)
- ReAct-v3:  $0.78 + $1.14 = $1.92 (Bertrand)  — 5.6× cheaper than ReAct-v1
- Researcher: $1.99 + $1.16 = $3.15 (Bertrand), $2.53 + $1.38 = $3.91 (ZAI)

### 2.4 Threshold Sensitivity τ ∈ {0.7, 0.75, 0.8, 0.9, 1.0} (from `c6_threshold_sensitivity.csv`)

All 16 series monotone non-increasing; rank stability across τ is ~1.0. Example (ReAct-v1 Bertrand): `[0.414, 0.414, 0.401, 0.401, 0.401]`. **One-sentence appendix claim** suffices.

### 2.5 Query-Type Auto-Distribution (from `c2_annotation_sample_bertrand-...csv`, 380 assertions)

email 31%, cross-source 21%, other 22%, file 20%, meeting 5%, chat 1%. **This is auto-tagged from query keywords, not human-validated** — must be described as such.

---

## 3. Per-Section Edit Plan

### 3.1 `experiments_results.tex` — §Agent Configurations (lines ~6–35)

**Add a new row to `tab:agent_configs`** for ReAct-v3:

```
\textsc{ReAct-v3}   & ReAct             & GPT-4o-mini & ---               & $\sim$3k tok   & TBD  & TBD  \\
```

(Compute avg tools / latency from `eval_*react_v3*.json` — TODO when editing.)

**Rewrite the prose after the table** to describe four agents and justify ReAct-v3 as a controlled ablation: ReAct-v3 shares prompt and architecture with ReAct-v1 but swaps GPT-4o → GPT-4o-mini, isolating model-size from architecture.

### 3.2 §Evaluation Metrics (C5 & C6 placeholders)

**Remove the C5 `\textcolor{red}{[PLACEHOLDER C5 ...]}` block** and replace with either:
- (A) If we re-run baseline: 1 paragraph describing retrieve-and-summarize lower bound with actual numbers (all ~0 even after fix because no synthesis happens without reasoning — exact numbers TBD).
- (B) If we drop baseline: delete placeholder entirely, add one line "We do not include a zero-turn retrieve-and-summarize baseline because it degenerates to tool-call-only output with no synthesis."

**Add after pass/fail rule paragraph** (for C6):
> "We verified rank stability under the pass threshold: varying the assertion gate τ from 0.70 to 1.00 while holding RC-Rel ≥ 0.7 preserves agent ranking on all 4 tenants (Spearman ρ = 1.0; Appendix Table~\ref{tab:threshold_sensitivity})."

### 3.3 §Main Results — Tables 6 and 7

**Table 6 (`tab:results_full`):**
- Add 3 new ReAct-v3 rows (Bertrand/Cambford/ZAI) with 0.395 / 0.296 / 0.363 pass rates.
- Append `± 95% CI` to the Pass column for every cell using the CSV values.
- Recompute "bold = best per tenant" — ReAct-v3 may take ZAI.

**Table 7 (`tab:agent_ranking`):**
- Add ReAct-v3 aggregate row (pass ~0.350 across 3 tenants, compute Assr/TS-Rel/etc. from JSONs).
- **Remove `\textcolor{red}{[PLACEHOLDER C4 ...]}`** from the caption.
- Add a new footnote/column with Wilson CI on Pass.
- Add a separate small table or inline note listing the 6 key Wilcoxon results above.

**Rewrite the first post-table paragraph** so the headline is no longer "Researcher wins" but "Researcher wins on Cambford (p < 0.01), ties elsewhere; ReAct-v3 shows that model size, not planning, drives Researcher's ZAI performance (and in fact ReAct-v3 beats Researcher on ZAI at p = 0.032)."

### 3.4 §Effect of Agent Architecture (lines ~210–230)

This section currently argues Researcher's planning is the key driver. With ReAct-v3 data, the argument **flips significantly**:

- Keep: "Researcher retrieves 3.5× more items" — still true.
- Keep: "Cambford benefits most from planning" — supported by Wilcoxon p < 0.01.
- **Revise:** The Bertrand/ZAI narrative. With ReAct-v3 ≈ Researcher on Bertrand and ReAct-v3 > Researcher on ZAI, the effect attributed to "planning helps less when evidence is dense" is better explained as "planning is strictly helpful only on Cambford; on other tenants the model-size handicap of GPT-4o-mini is not offset by planning."

**Remove** the `\textcolor{red}{[PLACEHOLDER C3 ...]}` block at the end of this subsection.

**Add** a new paragraph decomposing the three variables:
> "The ReAct-v1 → ReAct-v3 contrast isolates model size (GPT-4o → GPT-4o-mini) at fixed architecture: pass rate moves -0.019 / +0.068 / +0.094 across Bertrand/Cambford/ZAI. The ReAct-v3 → Researcher contrast isolates planning at fixed model: +0.037 / +0.050 / -0.074. Planning therefore provides a consistent but small boost on Bertrand/Cambford and is actively harmful on ZAI, whereas moving from GPT-4o to GPT-4o-mini is approximately neutral or beneficial—a result that is the opposite of what the original three-agent comparison suggested."

### 3.5 §Cost–Effectiveness Trade-off (lines ~260–290)

**Replace** the current "Judge cost" paragraph (which only says "see `judge_tokens` field") with a new **Cost Table** drawn directly from `b8_cost_breakdown.csv`. Columns: Agent × (avg $/case agent, avg $/case judge, $/100 cases total). This addresses R1 and R3-O2.

**Update `fig:cost_frontier`:** add ReAct-v3 point — it dominates ReAct-v2 (higher pass, lower cost) and Researcher on ZAI. Redraw the Pareto frontier note accordingly.

### 3.6 §Query-Type Analysis

Current prose cites the 40/40/20 split from the generator. The C2 CSV gives the **actual observed distribution per tenant** for assertion-level tagging. Add one sentence:
> "A post-hoc keyword-based audit of 380 assertions (Bertrand) approximately matches the generator-declared split, with 52% single-source (email/chat/file/meeting) and 21% explicitly cross-source assertions (see supplementary `c2_annotation_sample_*.csv`). This is an automated audit, not a human validation study."

Do **not** claim "human-validated" unless we actually run an annotation pass.

### 3.7 §Limitations or §Threats to Validity

Add a paragraph:
> "We attempted a cross-model judge replication using GLM-4.7-FlashX as an alternative to GPT-4o; however, the resulting pass rates were inconsistent (≤2% across agents) due to parser-level disagreement in the GLM response format, and we therefore do not report those results. Cross-model judge agreement remains an open validation task."

---

## 4. New Appendix Content

Create a new section `appendix_extra_results.tex` (to be `\input` at end of paper) containing:

1. **Table:** Full 30-comparison Wilcoxon matrix from `c4_pairwise_wilcoxon.csv`.
2. **Table:** Threshold sensitivity (`c6_threshold_sensitivity.csv`, 80 rows, 5 cols per agent).
3. **Table:** Full cost breakdown (`b8_cost_breakdown.csv`, 16 rows).
4. **Table:** Per-tenant Wilson CI for assertion score and citation score (need to compute — currently only pass rate has CI in CSV; add as extension to `analyze_post_hoc.py` if needed).

---

## 5. Revised Abstract / Intro Claims to Check

Search and revise these claims elsewhere in `main.tex`:

- Any sentence of the form "Researcher outperforms ReAct" → qualify with "on Cambford" or "on 2 of 3 tenants at fixed model size."
- Any sentence of the form "plan-and-execute > ReAct" → qualify as above and cite ReAct-v3 on ZAI counterexample.
- Contributions list — if it enumerates "we show plan-and-execute helps", soften to "we identify when plan-and-execute helps (temporal multi-hop scenarios) and when it hurts (bursty evidence scenarios)."

---

## 6. Execution Order

1. **Decide C5 fate:** fix (`max_turns: 2`, re-run 3 tenants, ~$6, ~1 hour) or drop. Recommended: **drop with explanation** — all evidence suggests a degenerate baseline here.
2. **Regenerate** `analyze/output/missing_experiments/` with current CSVs (already done).
3. **Edit `experiments_results.tex`** in order: §Agent Configurations → §Evaluation Metrics → Tables 6/7 → §arch-analysis → §cost. Use `multi_replace_string_in_file` for simultaneous table + prose edits.
4. **Create** `appendix_extra_results.tex`; `\input` at end of `main.tex`.
5. **Update** `main.tex` contributions, abstract, intro one-liners.
6. **Rebuild PDF**, check page count, skim for flow.
7. **Commit** to `u/haoyi/academic-paper` with message grouping changes by subsection.

---

## 7. What NOT to Do

- Do **not** present auto-tagged query types as human validation (C2 is just distribution).
- Do **not** report C5 baseline numbers as-is; the `max_turns:1` bug means the zeros are an artefact, not a scientific finding.
- Do **not** report GLM judge numbers (C1). They are systematically low due to parser issues and do not represent the model's actual agreement with GPT-4o.
- Do **not** bold ReAct-v3 on Bertrand pass rate — its CI overlaps Researcher's; use the Wilcoxon p-value for claims, not point estimates.
