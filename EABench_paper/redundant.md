# Redundant / Unnecessary Content Audit

Snapshot of outstanding redundancy and unnecessary content found in the current paper (`main.tex` and its included files). Items already fixed in prior passes (I1 judge-call count, I3 threshold-configurability claim, I5 burstiness value, I6 assertion weights, I7 planning-model caption, "five tenants" claim, "weighted assertions" language) are not listed here.

Severity: **H**igh = affects correctness/clarity, **M**edium = noticeable repetition, **L**ow = cosmetic.

---

## 1. Near-duplicate prose across sections

### D1 — Agent setup sentence duplicated in §5 intro and §5.1.1 [M]
- `main.tex` §5 Experimental Setup: *"All agents share the same embedding model (`text-embedding-ada-002`) and use GPT-4o-family models via Azure OpenAI: the two ReAct agents use GPT-4o while the Researcher agent uses GPT-4o-mini for both planning and execution."*
- `experiments_results.tex` §5.1.1: *"All three share the same embedding model (`text-embedding-ada-002`) and use GPT-4o-family models via Azure OpenAI: the two ReAct agents use GPT-4o while the Researcher agent uses GPT-4o-mini."*

**Fix:** Keep the detail in §5.1.1; in §5 replace with a one-line cross-reference.

---

### D2 — Researcher "61.6 items vs. 15–19" restated twice [M]
- `experiments_results.tex` §5.1.1: *"systematically broader retrieval (61.6 items retrieved per case vs. 15--19 for the reactive agents)"*
- `experiments_results.tex` §5.2.1: *"Researcher retrieves 61.6 items per case versus 15--19 for the reactive agents---a factor of ~3.5×"*

**Fix:** §5.1.1 is a configuration description; the retrieval-ratio analysis belongs only in §5.2.1. Drop the parenthetical from §5.1.1.

---

### D3 — ReAct-v1 prompt behaviors listed twice [M]
- §5.1.1 (config): *"eight fully worked Thought→Tool examples … dual-term person lookup, pronoun-to-ID resolution, multi-query decomposition, and detailed citation formatting."*
- §5.2.2 (Effect of Prompt Engineering): same behaviors re-enumerated.

**Fix:** §5.1.1 should state only the prompt size and style ("eight worked examples"). The behavioral breakdown belongs in §5.2.2.

---

### D4 — Researcher planner mechanism described in three places [M]
- `methodology_agent_runtime.tex` §3.2.2: mechanism (planner → execute)
- `experiments_results.tex` §5.1.1: full "four required capabilities" paragraph
- `experiments_results.tex` §5.2.1: "Before issuing any tool call, Researcher prompts GPT-4o-mini to produce a structured research plan…"

**Fix:** §3.2.2 is the canonical mechanism. §5.1.1 should only state *which* configuration runs. §5.2.1 should explain observed behavior, citing §3.2.2 rather than restating the mechanism.

---

### D5 — Three query types defined in four places [M]
1. `methodology_eval_dataset.tex` §3.4.1 — full definitions with examples
2. Table `tab:query_types` — formal table restating the same
3. `main.tex` §5 setup — short enumeration
4. `experiments_results.tex` §5.2.4 — *"targeted artifact search (single-artifact lookup), multi-hop reasoning (cross-artifact reasoning), and comprehensive report (multi-source synthesis)"*

**Fix:** Keep §3.4.1 as canonical. Everywhere else use short names with `\ref{sec:method_evaldataset}`.

---

### D6 — Scenario stressors restated in §4 and §5.2.3 [M]
§4 scenario subsections describe design intent (e.g., *"policy drafts, meeting discussions, and follow-up emails over multi-week windows"*), and §5.2.3 Scenario-Level Analysis restates nearly the same stressor in empirical framing (*"reconstructing policy evolution across weeks of committee emails"*).

**Fix:** §4 = design intent; §5.2.3 = empirical observations only. Strip scenario descriptions from §5.2.3.

---

### D7 — §4.4 re-describes the generation pipeline [L]
`scenarios_datasets.tex` §4.4 opens with a three-step recap of the generation pipeline (daily story prompt → summary prompts → content prompts) that duplicates §3.3.

**Fix:** Replace with one sentence + `\ref{sec:method_generation}`.

---

### D8 — Pass/fail criteria rationale split awkwardly [L]
- `methodology_eval_harness.tex` §3.5.3 lists the 0.75 / 0.7 thresholds but gives no rationale.
- `experiments_results.tex` §5.1.2 repeats the same rule *and* provides the only motivation ("rejects responses that miss more than one in four gold facts").

**Fix:** Move the rationale sentences to §3.5.3; §5.1.2 cites them.

---

## 2. List + table pairs that convey the same content

### D9 — §3.5.2 itemize list vs. `tab:eval_metrics` [M]
The `itemize` block listing judge-based + deterministic metrics is immediately followed by `tab:eval_metrics` covering the same seven metrics. The two together occupy ~half a page with no added information.

**Fix:** Keep the table; drop the itemize (or vice-versa).

---

### D10 — §3.3.2 prose vs. `tab:generation_pipeline` [L]
Five-stage generation pipeline is described both as prose paragraphs and as a five-row table. The table is sufficient.

**Fix:** Shrink prose to a framing sentence + table reference.

---

### D11 — §3.1 prose vs. `tab:pipeline_artifacts` [L]
The six pipeline stages are narrated in §3.1 prose and tabulated in `tab:pipeline_artifacts`. Noticeable overlap.

**Fix:** Let the prose describe only the flow/interfaces between stages; the table lists artifacts.

---

### D12 — Interactive debugging paragraph vs. `tab:debug_surfaces` [L]
§3.6.2 enumerates debugging surfaces in prose, then `tab:debug_surfaces` lists the same six items. One of them is redundant.

**Fix:** Keep the table; shorten prose to one sentence.

---

## 3. Figures that duplicate each other

### D13 — `fig:pass_rate` and `fig:assertion_score` redundant with `fig:metrics_heatmap` [M]
`fig:metrics_heatmap` already covers pass rate and assertion score across all nine agent × tenant cells. `fig:pass_rate` and `fig:assertion_score` are single-metric bar charts over the same data.

**Fix:** Remove both single-metric figures and cite the heatmap.

---

### D14 — `fig:latency_vs_pass` and `fig:cost_frontier` cover overlapping argument [L]
Both figures plot three data points (three agents) on cost-vs-quality axes. §5.2.5 doesn't use them to make distinct points.

**Fix:** Merge into a single two-panel figure, or keep only one.

---

### D15 — `fig:citation_decomposition` redundant with the heatmap's RC-Rel / TS-Rel rows [L]
The TS-Rel vs. RC-Rel comparison is visible in `fig:metrics_heatmap` and stated in the §5.1.3 aggregate table. `fig:citation_decomposition` adds a second view of the same numbers.

**Fix:** Consider dropping; the argument in the text ("ReAct-v1 leads TS-Rel; Researcher leads RC-Rel") is carried by the table and heatmap.

---

## 4. Unnecessary remaining artifacts

### D16 — `methodology_agent_runtime.tex` YAML listing still shows `temperature: 0.7` [L]
Temperature was stripped from all prose and tables. The canonical configuration listing (`lst:runtime_yaml`) still contains `parameters: {temperature: 0.7}`. Same issue in `methodology_eval_harness.tex` judge listing (`temperature: 0.0`).

**Fix:** Remove the `parameters:` lines from both YAML listings, or drop that whole key. (Previously flagged as I2 and left intentionally; revisit for consistency.)

---

### D17 — `main_bak.tex` kept in repo alongside active `main.tex` [L]
`EABench_paper/main_bak.tex` is a 700+ line backup of a prior draft. It is not included from `main.tex`, but it is still part of the working directory and shows up in searches.

**Fix:** Move to a `archive/` subfolder or delete.

---

### D18 — Placeholder blocks still present in `\textcolor{red}{…}` [H]
Three open `[PLACEHOLDER …]` blocks remain in the paper body:
- C2 (`methodology_eval_harness.tex`) — human validation study
- C3 (`experiments_results.tex` §5.2.1) — ReAct-v3 ablation
- C4 (`experiments_results.tex` Table `tab:agent_ranking`) — Wilson CIs and Wilcoxon tests
- C5 (`experiments_results.tex` §5.1.2) — retrieval-only baseline

Each is rendered in red and will appear as unfinished TODOs to a reviewer.

**Fix:** Either execute the missing work or remove the placeholders with a brief sentence acknowledging the limitation. (They are substantive, not merely redundant — flagged here because they are the most immediately visible "unnecessary-looking" content to a reader.)

---

### D19 — Large commented-out figure placeholder blocks [L]
Several `\begin{figure}` environments contain long commented-out `\fbox{\parbox{…}}` descriptions of the figure that was requested from a designer before the PNG was produced (e.g., in `main.tex` line ~160, `methodology_data_generation.tex`, `methodology_agent_runtime.tex`, `methodology_eval_harness.tex`). These are typically 20–40 lines each of TikZ/prose specification no longer rendered.

**Fix:** Move to a `figures/_specs/` directory or delete — they clutter the source without affecting output.

---

### D20 — Conclusion re-enumerates the contributions [L]
The conclusion (§6) lists *"it joins four ingredients in a single platform"* — an enumeration redundant with the abstract and the intro. Now that contributions have been itemized in three points, the conclusion wording is both stale (still says *four*) and duplicative.

**Fix:** Rewrite the closing to synthesize outcomes rather than re-list contributions; update the count if the list is kept.

---

## 5. Minor wording duplication (cosmetic)

| # | Location | Note |
|---|---|---|
| W1 | Abstract vs. Intro | Both say *"hot-swappable … without code changes"* in near-identical phrasing. |
| W2 | `tab:agent_configs` vs. §5.1.1 | Prompt-size and avg.\ tool counts appear in the table and are re-stated in prose. |
| W3 | `methodology_overview.tex` §3.1 last paragraph | *"causal experimentation possible"* — tone shift; could be removed without losing meaning. |

---

## Summary

- **6 duplicate prose blocks** (D1–D6) — trim one occurrence in each.
- **4 list/table pairs** (D9–D12) — keep one representation each.
- **3 figure redundancies** (D13–D15) — collapse or drop.
- **5 leftover artifacts** (D16–D20) — YAML inconsistency, backup file, placeholders, figure-spec comments, stale conclusion list.

Total page savings if all fixes applied: approximately **2–3 pages** without loss of technical content.
