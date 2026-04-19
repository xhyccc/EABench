# EABench Revision Plan

Based on the three peer reviews in `reviews.md`. Items are grouped by what is needed:
- **[Text]** — manuscript edit only, no new experiments
- **[Experiment]** — requires new runs; placeholder `\textcolor{red}{...}` to be inserted in the LaTeX source until results are available

---

## Part A — Query Type Definitions (User Issue #2)

**Problem.** The paper describes the three query types in a way that does not match the actual generation prompts.

### Current paper text (methodology_eval_dataset.tex, §3.2)

| Paper term | Paper description |
|---|---|
| Needle-in-a-haystack retrieval | "ask the agent to locate a specific artifact or a very small set of artifacts without ever naming internal identifiers explicitly" |
| Multi-step reasoning | "require the agent to follow a dependency chain across multiple modalities" |
| Deep-dive report generation | "ask for a coherent summary of an incident or initiative spread across several days of activity" |

### What the prompts actually say (examples/generation/default_prompts.yaml)

| Prompt | What it generates |
|---|---|
| `generate_search_eval` | **Complex natural-language search queries** that imply specific constraints (time, author, artifact type, keywords) and are designed to retrieve a specific item or a small result set. Queries must NOT explicitly mention internal IDs. User is assigned plausibly (e.g., a recipient of the target email). |
| `generate_multihop_eval` | **Multi-hop reasoning queries** that require finding information in one artifact to answer a question about another, or tracing a chain of events. Example: "Who was the organizer of the meeting discussed in Sarah's email about 'Budget'?" |
| `generate_report_eval` | **Comprehensive report requests** — summaries, timelines, or analyses of a specific topic found across a time window. Must be grounded in contiguous event context available in the corpus. |

### Key discrepancies to fix

1. **"Needle-in-a-haystack" is the wrong term.** In the literature this phrase denotes long-context retrieval where context length is the difficulty variable. Our search queries are *constrained natural-language searches* where difficulty comes from implicit multi-dimensional constraints (who, when, what type, what topic) — not from context length. Rename to **"Targeted Artifact Search"** throughout the paper.

2. **The paper implies search queries target a single artifact**, but the prompt says "a specific item or a *small set of items*." The paper should say "one or a small number of target artifacts" to match the prompt.

3. **The paper implies the search pass shuffles artifact summaries** ("The first pass shuffles artifact summaries and generates needle-in-a-haystack queries"). This is an implementation detail. The description should focus on the *semantic intent* of the query type as defined by the prompt, not the shuffling strategy.

4. **"Multi-step" vs "multi-hop."** The paper uses "multi-step reasoning" but the prompt key is `generate_multihop_eval` and the LLM instructions use "multi-hop." For consistency with the codebase and the literature, rename to **"Multi-Hop Reasoning"** throughout.

5. **Report query scope.** The paper says "spread across several days" which comes from the 3–7 day sampling window implementation detail. The prompt defines it more broadly as "summary, timeline, or analysis of a specific topic." Revise to reflect the broader intent.

### Revised table (replace in methodology_eval_dataset.tex)

| Query type | Definition (from generation prompt) | Primary capability tested |
|---|---|---|
| Targeted artifact search | Natural-language query implying constraints on time, author, artifact type, or topic; targets a specific item or small result set without naming internal IDs | Targeted retrieval under natural phrasing and user-level access control |
| Multi-hop reasoning | Query that requires finding information in one artifact to answer a question about another, or tracing cross-artifact event chains | Cross-modal reference resolution and dependency-chain reasoning |
| Comprehensive report | Request for a summary, timeline, or analysis of a specific topic grounded in a contiguous window of tenant activity | Long-form synthesis, temporal organization, and citation-grounded summarization |

### Affected files
- `methodology_eval_dataset.tex` — revise §3.2 prose, Table "Automatically generated query types", and the "three passes" paragraph
- `main.tex` — check any mention of query types in §4 (Scenarios) and §5 (Experiments)
- `experiments_results.tex` — §5.6 query-type breakdown: rename axis labels and section heading to match new terms
- `scenarios_datasets.tex` — any mention of query-type distribution

---

## Part B — Required Fixes (Text Only, No New Experiments)

### B1. Missing bibliography entry — `goh2008burstiness` [Text]

**Files:** `bibliography.bib`

Add the following entry:
```bibtex
@article{goh2008burstiness,
  author  = {Goh, Kwang-Il and Barabási, Albert-László},
  title   = {Burstiness and memory in complex systems},
  journal = {EPL (Europhysics Letters)},
  volume  = {81},
  number  = {4},
  pages   = {48002},
  year    = {2008},
  doi     = {10.1209/0295-5075/81/48002}
}
```

### B2. Remove `\textcolor{blue}{}` draft artifacts [Text]

**Files:** `main.tex`, `methodology_eval_dataset.tex`, `methodology_overview.tex`, `methodology_data_generation.tex`, `methodology_agent_runtime.tex`, `methodology_eval_harness.tex`, `methodology_interactive.tex`, `scenarios_datasets.tex`, `experiments_results.tex`

Run: `sed -i '' 's/\\textcolor{blue}{/\n/g; s/^}//' *.tex` (validate manually after).

Alternatively do a global find-replace of `\textcolor{blue}{\(.*\)}` → `\1` per file.

### B3. Fix malformed nested `figure` inside `table` [Text]

**File:** `experiments_results.tex`

The metrics heatmap figure is placed inside a `\begin{table}...\end{table}` environment. Move it to a standalone `figure` environment outside the table.

### B4. Fix duplicate WorkArena entry in Related Work [Text]

**File:** `main.tex`

WorkArena appears twice in Related Work (§2) with slightly different descriptions. Merge into one citation with a consolidated description.

### B5. Rename "needle-in-a-haystack" throughout [Text]

(Covered under Part A, but listed here as a standalone find-replace task.)

**Files:** all `*.tex` in `EABench_paper/`

Replace all occurrences of "needle-in-a-haystack" and "Needle-in-a-haystack" with "targeted artifact search" (agreed term from Part A).

### B6. Justify the 40/40/20 query-type target split [Text]

**File:** `methodology_eval_dataset.tex` or `scenarios_datasets.tex`

Add one sentence explaining the rationale for the 40/40/20 generation target (e.g., "Search and multi-hop cases are more numerous because they offer the finest-grained diagnostic signal; report cases require a larger context window and are generated at lower frequency per history segment"). Also acknowledge that observed splits deviate from the target because generators produce variable-length batches.

### B7. Remove "extreme configurability" overclaim [Text]

**File:** `main.tex` (Abstract)

Replace "extreme configurability" with a measured description, e.g., "full configurability of LLM backbone, agent architecture, tool set, system prompt, and evaluation harness via declarative YAML files."

### B8. Add precise cost breakdown to cost table [Text]

**File:** `experiments_results.tex`

Add a row or footnote to the cost-effectiveness table reporting (a) judge evaluation cost per case (4 LLM calls) and (b) total cost = generator + runtime + judge, in USD per 100 cases for each agent configuration. Use logged token counts already available in the JSON result files.

### B9. Acknowledge pass-rate binary threshold choice [Text]

**File:** `methodology_eval_harness.tex`

Add one sentence clarifying why assertion score = 1.0 (not 0.9 or 0.8) was chosen as the pass threshold, e.g., reference to enterprise compliance requirements where partial satisfaction is operationally unacceptable. This preempts the reviewer concern without requiring a sensitivity experiment (though the experiment is recommended — see C6 below).

### B10. Clarify query classification heuristic in analysis [Text]

**File:** `experiments_results.tex` §5.6

The analysis classifies cases by query type using a post-hoc entity-count heuristic (entity_count ≤ 1 → search/fact-check; presence of action verb → report; else → multi-hop). State this heuristic explicitly in the text and note that analysis-time classifications are approximate because the ground-truth `query_type` field is available in the evaluation dataset JSON and could be used directly in future work.

---

## Part C — New Experiments Required

The following items require running experiments. Until results are available, insert `\textcolor{red}{[PLACEHOLDER: ...]}` in the corresponding sections of the LaTeX source.

### C1. Cross-Model Evaluation (generator–judge circularity) [Experiment]

**Reviewers:** R1-C1 (Critical), R2-C1 (Critical)

**What to do:** Re-run evaluation of at least one agent (recommend ReAct-v1, as the best-performing ReAct variant) on one tenant (recommend Cambford) using a judge from a different model family than GPT-4o. Candidate: Claude 3.5 Sonnet or Gemini 1.5 Pro.

**What to report:** Pass rate and assertion score under alternative judge. If the ranking of architectures is preserved, this is strong evidence against self-preference bias.

**Placeholder location:** `experiments_results.tex` §5.4 (Cross-Model Evaluation subsection, which currently exists as a framework description with no results).

```latex
\textcolor{red}{[PLACEHOLDER: Table reporting ReAct-v1 and Researcher pass rate / assertion score on Cambford under GPT-4o judge vs. [alternative model] judge. Expected to demonstrate ranking stability across judge families.]}
```

### C2. Human Assertion Validation Study [Experiment]

**Reviewers:** R1-C2 (Critical), R2-C1 (Critical), R3-C1 (Important)

**What to do:** Recruit 2–3 annotators. Sample 50 cases per query type × 1 tenant (150 cases total from e.g. Bertrand). For each case, annotators judge: (a) Is the assertion grounded in the corpus? (b) Is the assertion satisfiable by a correct answer? (c) Is the assertion non-trivial (not immediately obvious without search)? Report Cohen's κ across annotators and the false-positive rate (assertions deemed invalid by majority vote).

**What to report:** Grounding rate, satisfiability rate, non-triviality rate, inter-annotator κ — broken down by query type.

**Placeholder location:** `methodology_eval_harness.tex` after the Assertion Generation subsection.

```latex
\textcolor{red}{[PLACEHOLDER: Human validation study. N=150 sampled assertions (50 per query type, Bertrand tenant). Annotators: 3. Report grounding rate, satisfiability rate, inter-annotator κ. Results expected to confirm assertion validity.]}
```

### C3. Architecture Ablation — Isolating Planning from Model/Temperature [Experiment]

**Reviewers:** R1-C3 (Critical), R2-C3 (Critical), R3-C2 (Important)

**What to do:** Add a fourth agent configuration: ReAct with GPT-4o-mini at T=0.0 (identical model and temperature to Researcher, but ReAct architecture instead of Plan-and-Execute). This isolates the architectural contribution from the LLM backbone and decoding strategy.

**What to report:** Pass rate, assertion score, tool calls per case for this new configuration alongside the existing three. If the new configuration scores below Researcher, the planning advantage is confirmed.

**Placeholder location:** `experiments_results.tex` §5.3 (Architecture Analysis subsection).

```latex
\textcolor{red}{[PLACEHOLDER: Add ReAct-v3 (GPT-4o-mini, T=0.0, ReAct architecture) as a controlled ablation isolating the architectural variable. Results table updated with 4 agent configurations.]}
```

### C4. Confidence Intervals and Significance Tests [Experiment]

**Reviewers:** R1-C5 (Important), R2-C5 (Important), R3-C3 (Important)

**What to do:** For the existing result data (already computed over 162–201 binary pass/fail outcomes per cell), compute:
- Wilson 95% confidence intervals for pass-rate estimates (binary outcome, closed form — no new runs needed)
- Paired Wilcoxon signed-rank test for key pairwise comparisons: ReAct-v1 vs. Researcher (overall), ReAct-v1 vs. ReAct-v2 (prompt engineering effect), within-tenant comparisons (Cambford 52% claim)

**Note:** The CI computation requires no new LLM calls — the per-case pass/fail outcomes are already in the results JSON files. This is technically a text/analysis change, but it requires careful re-analysis of existing data so it is categorized here.

**What to report:** Update Table (main results) with ± CI columns. Add a sentence per key comparison stating p-value from Wilcoxon test.

**Placeholder location:** `experiments_results.tex`, results table caption and §5.2.

```latex
\textcolor{red}{[PLACEHOLDER: Add 95% Wilson CI columns to main results table. Add Wilcoxon signed-rank p-values for: (1) ReAct-v1 vs. Researcher overall pass rate, (2) ReAct-v1 vs. ReAct-v2 overall pass rate, (3) Researcher vs. ReAct-v1 on Cambford pass rate.]}
```

### C5. Retrieval-Only Baseline [Experiment]

**Reviewers:** R2-C4 (Important)

**What to do:** Implement and evaluate a simple baseline agent: retrieve the top-$k$ documents returned by the first tool call, concatenate their text, and pass to the LLM to summarize. No multi-turn reasoning, no planning. Run on all three tenants.

**What to report:** Pass rate, assertion score, tool calls per case for the baseline. This anchors the reported scores — if the baseline achieves, say, 15% pass rate, then the best agent's 35.5% represents a meaningful 2.4× improvement.

**Placeholder location:** `experiments_results.tex` §5.1 or a new subsection before §5.2.

```latex
\textcolor{red}{[PLACEHOLDER: Retrieval-only baseline: top-k retrieve-and-summarize, no multi-turn reasoning. Report pass rate, assertion score per tenant. Provides lower-bound anchor for interpreting agent scores.]}
```

### C6. Pass-Rate Threshold Sensitivity [Experiment]

**Reviewers:** R1-M2 (Minor but methodologically important)

**What to do:** Using existing per-assertion scores (no new LLM calls), re-compute "pass rate" at thresholds 0.8, 0.9, and 1.0 (current). Report how agent rankings change.

**Placeholder location:** `methodology_eval_harness.tex` or Appendix.

```latex
\textcolor{red}{[PLACEHOLDER: Sensitivity table showing pass rates for all three agents under thresholds τ ∈ {0.8, 0.9, 1.0}. Confirms that relative agent rankings are stable across threshold choices.]}
```

---

## Part D — Optional / Lower Priority

These items were raised by reviewers but are not blocking for acceptance. Address if time permits.

| Item | Reviewer | Action |
|---|---|---|
| Interactive interface usability | R3-O3 | Add one sentence clarifying the interface is described as a practical development tool rather than a formally evaluated contribution |
| LLM judge human agreement | R2-C1 | Partially addressed by C2 (human assertion validation); if assertion scores correlate with human judgments in C2, this is partially satisfied |
| Latency breakdown for Researcher | R3-O5 | Add note on where the 65s is incurred (planning vs. execution vs. judge); data may be available in result JSON timestamps |
| Comparison table (Table 2) construction method | R3-O4 | Add footnote clarifying how feature presence was determined for each system |
| Multi-run variance for temperature stochasticity | R2-C5 | Lower priority; the confound is more substantially addressed by C3 (architecture ablation) |

---

## Revision Priority Order

1. **Do immediately (no experiments):** B1 (citation), B2 (blue text), B3 (nested figure/table), B4 (WorkArena duplicate), **Part A (query type redefinition)**
2. **Do next (analysis of existing data):** C4 (confidence intervals — no new LLM calls), B8 (cost breakdown from logs), B10 (query classification), C6 (threshold sensitivity from existing data)
3. **New experiments (plan and run):** C5 (retrieval baseline — cheapest), C1 (cross-model judge), C3 (architecture ablation)
4. **Largest effort:** C2 (human annotation study)
5. **Polish:** B5–B9, D items
