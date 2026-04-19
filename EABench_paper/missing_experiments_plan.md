# Plan of Missing Experiments

Derived from `revision_plan.md` Part C and reviewer comments (R1/R2/R3).
Execution driver: `scripts/run_missing_experiments.sh`.

---

## Overview

| ID  | Experiment                                 | Blocking | New LLM calls? | Cost (approx.) | Priority |
| --- | ------------------------------------------ | -------- | -------------- | -------------- | -------- |
| C4  | 95 % Wilson CI + Wilcoxon on existing JSON | yes      | **no**         | 0              | **P0**   |
| C6  | Pass-threshold sensitivity (τ=0.7/0.8/0.9) | yes      | **no**         | 0              | **P0**   |
| B8  | Cost breakdown from logged token counts    | no       | **no**         | 0              | P0       |
| C3  | ReAct-v3 ablation (GPT-4o-mini + ReAct)    | yes      | yes (agent)    | ≈ $18          | **P1**   |
| C5  | Retrieval-only baseline                    | yes      | yes (agent)    | ≈ $6           | P1       |
| C1  | Cross-model judge (GLM-4.7-FlashX)         | yes      | yes (judge)    | low (Zhipu)    | **P1**   |
| C2  | Human assertion validation (N=150)         | yes      | no (annotator) | labour         | P2       |

Estimates assume 525 cases × 1 run each. P0 items reuse existing result JSONs in `python/results/`.

---

## C4 — Confidence Intervals & Significance Tests [no new runs]

**Reviewers:** R1-C5, R2-C5, R3-C3.

**Inputs:** `python/results/eval_*_2026041*.json` (latest per tenant × agent).

**Method:**
- Per (agent, tenant) cell, compute Wilson 95 % CI on pass rate from the per-case pass/fail list.
- Paired Wilcoxon signed-rank on matched case IDs across agent pairs:
  1. ReAct-v1 vs Researcher (overall, and on Cambford only — the 52 % claim).
  2. ReAct-v1 vs ReAct-v2 (prompt effect).
  3. Researcher vs ReAct-v2 (architecture effect with matched verbosity tier).
- Bootstrap 95 % CI (n=10 000) on mean assertion score and RC-Rel per cell.

**Deliverable:** Updated Table 6 columns (±CI) and one p-value sentence per comparison in §5.2.

**Script:** `scripts/analyze_post_hoc.py --mode ci-significance`.

---

## C6 — Threshold Sensitivity [no new runs]

**Reviewers:** R1-M2.

**Method:** Using per-assertion scores already in the JSON, recompute pass rate with τ ∈ {0.70, 0.75, 0.80, 0.90, 1.00} and citation gate fixed at 0.7. Report pass-rate table and rank-correlation (Spearman) between τ-variants.

**Deliverable:** Appendix table; a sentence in §5.1.2 confirming rank stability.

**Script:** `scripts/analyze_post_hoc.py --mode threshold-sensitivity`.

---

## B8 — Cost Breakdown [no new runs]

**Reviewers:** R1 minor, R3-O2.

**Method:** Sum `prompt_tokens` and `completion_tokens` already logged per case, apply Azure GPT-4o list price ($2.50 / 1M input, $10 / 1M output) and GPT-4o-mini price ($0.15 / $0.60). Separate agent-loop cost from judge cost.

**Deliverable:** Revised cost-effectiveness table with (a) agent-only, (b) judge-only, (c) total USD per 100 cases.

**Script:** `scripts/analyze_post_hoc.py --mode cost`.

---

## C3 — Architecture Ablation (ReAct-v3) [new runs]

**Reviewers:** R1-C3, R2-C3, R3-C2.

**Design.** Hold **model = GPT-4o-mini** and **temperature = 0.0** constant (matching Researcher). Vary only the architecture: ReAct loop instead of Plan-and-Execute. This isolates the planning contribution from model-size and decoding effects.

**Config:** `examples/agents/react_agent_v3.yaml` (new). Reuses ReAct-v2's condensed system prompt verbatim so prompt verbosity is also held constant.

**Run matrix:** 3 tenants × 1 agent × eval set = 525 cases.

**Success criterion:** If ReAct-v3 < Researcher on pass rate (statistically, per C4), the planning advantage is confirmed. If ReAct-v3 ≈ Researcher, the advantage was the small-model/deterministic-decoding combination.

**Script section:** `$ bash scripts/run_missing_experiments.sh c3`.

---

## C5 — Retrieval-Only Baseline [new runs]

**Reviewers:** R2-C4.

**Design.** A deliberately weak reference point: call `search_email` once with the verbatim query, concatenate the top-5 results, and instruct a single-turn GPT-4o-mini call to answer from that context only. No tool-use loop, no people-ID resolution.

**Config:** `examples/agents/retrieval_baseline.yaml` (new — sets `max_tool_iterations: 1` and an abbreviated prompt that forbids further tool calls after the first search).

**Run matrix:** 3 tenants × 525 cases.

**Deliverable:** New first row in Table 6 anchoring the pass-rate floor.

**Script section:** `$ bash scripts/run_missing_experiments.sh c5`.

---

## C1 — Cross-Model Judge [new runs]

**Reviewers:** R1-C1, R2-C1.

**Design.** Re-judge **existing** agent trajectories (no new agent runs needed) with a non-OpenAI judge. We use **GLM-4.7-FlashX** from Zhipu AI via its OpenAI-compatible endpoint. GLM is developed independently of the GPT-4o family and trained on different data, so a GLM judge provides a genuine cross-family validity check against the self-preference concern.

**Scope to keep cost bounded:** Judge only ReAct-v1 and Researcher on all three tenants (2 × 525 = 1 050 cases × (|assertions|+2) judge calls).

**Method:**
1. Extract `tool_calls` and `response` from each case in the existing JSON.
2. Re-invoke the judge prompts through the GLM OpenAI-compatible endpoint (`https://open.bigmodel.cn/api/paas/v4`).
3. Compare pass-rate rankings to the GPT-4o judge results. Report Spearman rank correlation of per-case assertion scores as the self-preference diagnostic.

**Config:** `examples/evals/glm_judge.yaml` (new — identical prompts, provider set to `openai` with GLM `base_url`).

**Prereq:** `OPENAI_API_KEY` and `OPENAI_API_BASE` in `.env` (already present in this workspace). Re-judge harness: `scripts/rejudge_with_glm.py` (new).

**Script section:** `$ bash scripts/run_missing_experiments.sh c1`.

---

## C2 — Human Assertion Validation [new labour, no code here]

**Reviewers:** R1-C2, R2-C1, R3-C1.

**Out of scope for the automation script.** Run offline:
1. Sample 50 cases per query type from Bertrand (stratified random). `scripts/analyze_post_hoc.py --mode sample-for-annotation` produces the CSV.
2. Three annotators independently label each assertion on (grounded, satisfiable, non-trivial).
3. Compute Cohen's κ pairwise and Fleiss' κ overall.

**Deliverable:** One additional subsection in `methodology_eval_harness.tex` reporting κ and false-positive rates.

---

## Execution Order

1. **Today (zero cost):** C4 + C6 + B8 — run `scripts/analyze_post_hoc.py --mode all`.
2. **Overnight (≈$6):** C5 retrieval baseline.
3. **Overnight (≈$18):** C3 architecture ablation.
4. **Next day (low cost, Zhipu pricing):** C1 cross-model judge using existing `OPENAI_API_KEY` pointed at the GLM endpoint.
5. **Manual:** C2 human annotation, after P0/P1 results land.

## Tracking

Each experiment writes to `python/results/` with a filename pattern:
```
eval_{tenant}_{agent_id}_{yyyymmdd_HHMMSS}.json
```
Post-hoc analyses write to `analyze/output/missing_experiments/`.
