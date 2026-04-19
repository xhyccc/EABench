# Revision Plan 2 — Redundancy, Duplication, and Inconsistency Audit

This document records every discovered instance of redundant, duplicated, or inconsistent content across the EABench paper. Items are grouped by type and ordered by severity.

---

## 1. Near-Verbatim Duplicate Passages

### R1 — Agent configuration opening sentence duplicated

**Location A** — `main.tex` §5 Experimental Setup (~line 425):
> "All agents share the same embedding model (`text-embedding-ada-002`) and use GPT-4o-family models via Azure OpenAI: the two ReAct agents use GPT-4o while the Researcher agent uses GPT-4o-mini for both planning and execution."

**Location B** — `experiments_results.tex` §5.1.1 Agent Configurations:
> "All three share the same embedding model (`text-embedding-ada-002`) and use GPT-4o-family models via Azure OpenAI: the two ReAct agents use GPT-4o while the Researcher agent uses GPT-4o-mini."

**Fix:** Remove the sentence from `main.tex` §5 setup (or keep a one-line pointer). The detail belongs in §5.1.1.

---

### R2 — Researcher retrieval count stated twice with near-identical phrasing

**Location A** — `experiments_results.tex` §5.1.1 (agent description):
> "resulting in systematically broader retrieval (61.6 items retrieved per case vs. 15--19 for the reactive agents)"

**Location B** — `experiments_results.tex` §5.2.1 (architecture analysis):
> "Researcher retrieves 61.6 items per case versus 15--19 for the reactive agents—a factor of ~3.5×."

**Fix:** Keep the detailed version with the factor in §5.2.1. In §5.1.1, replace with a forward cross-reference ("see Section 5.2.1 for retrieval statistics").

---

### R3 — ReAct-v1 prompt description duplicated

**Location A** — `experiments_results.tex` §5.1.1:
> "a verbose system prompt (~3,000 tokens) containing eight fully worked Thought→Tool examples. These examples concretely demonstrate several critical behavioral patterns: dual-term person lookup, pronoun-to-ID resolution, multi-query decomposition, and detailed citation formatting."

**Location B** — `experiments_results.tex` §5.2.2 Effect of Prompt Engineering:
> "ReAct-v1's eight fully worked examples concretely demonstrate each behavioral pattern: the agent sees a complete Thought→Tool→Observation chain for dual-term person lookup, pronoun resolution, multi-query decomposition, Python analytics, and citation formatting."

**Fix:** §5.1.1 should give the brief factual description (prompt size, style). The behavioral detail belongs in §5.2.2; §5.1.1 should cross-reference it.

---

### R4 — Pass/fail criteria defined in nearly identical words in two sections

**Location A** — `methodology_eval_harness.tex` §3.5.3 Pass/Fail Criteria:
> "A case is marked as passed when both of the following conditions hold simultaneously: Assertion score ≥ 0.75 … Response-citation quality ≥ 0.7 …"

**Location B** — `experiments_results.tex` §5.1.2 Evaluation Metrics:
> "A case is marked passed when Assr. ≥ 0.75 and RC-Rel ≥ 0.7. The assertion gate rejects responses that miss more than one in four gold facts; the citation gate rejects responses that lack a sufficiently grounded references section."

**Note:** The two-section split is intentional (§3.5 = capability, §5.1.2 = experiment instantiation), but the rationale text (assertion gate / citation gate explanation) currently appears only in §5.1.2. The same rationale appears nowhere in §3.5, so the reader of §3.5 sees thresholds with no motivation. **Fix:** Add a one-sentence motivation per gate in §3.5; shorten §5.1.2 to cite §3.5 for the criteria and add only the experiment-specific rationale.

---

### R5 — Scenario stressor descriptions repeated in §4 and §5

The three scenario subsections in §4 (Education, Law Firm, Software Company) and the per-tenant paragraphs in §5.2.3 (Scenario-Level Analysis) describe overlapping content:

| §4 text | §5.2.3 text |
|---|---|
| "queries that require the agent to connect policy drafts, meeting discussions, and follow-up emails over multi-week windows" (§4.1) | "cases frequently require reconstructing policy evolution across weeks of committee emails and subsequent meeting threads" (Cambford paragraph) |
| "answers frequently require the agent to combine people search, chat retrieval, meeting lookup, and file inspection" (§4.3) | "often involve tracing an incident or product decision through a dense cluster of same-day engineering chats, follow-up emails, and sprint meetings" (ZAI paragraph) |
| "same natural-language request may be answerable for a partner, partially answerable for a staff attorney, and intentionally blocked for a consultant" (§4.2) | Access control not revisited for Bertrand in §5.2.3—creating an asymmetry |

**Fix:** §4 subsections should describe the scenario design intent (what is stressed and why). §5.2.3 should present only the empirical observations from the evaluation, citing §4 for context. Remove restatements of scenario design from §5.2.3.

---

## 2. Information Repeated Across Sections (Cross-Reference Candidates)

### R6 — Three query types explained four times

Defined in:
1. `methodology_eval_dataset.tex` §3.4.1 (full definitions with examples)
2. Table `tab:query_types` (formal table)
3. `main.tex` §5 Experimental Setup: "covering three query types: targeted artifact search, multi-hop reasoning, and comprehensive report"
4. `experiments_results.tex` §5.2.4 Query-Type Analysis: "The evaluation set comprises three query categories … targeted artifact search (single-artifact lookup), multi-hop reasoning (cross-artifact reasoning), and comprehensive report (multi-source synthesis)"

**Fix:** Retain the full definition in §3.4.1 and the table. All other occurrences should use the short names only and cross-reference §3.4.1.

---

### R7 — Tenant sizes stated three times

| Location | Text |
|---|---|
| `scenarios_datasets.tex` §4.4 Dataset Statistics | "Bertrand & Co., 41 users … Cambford, 62 users … ZAI, 165 users" |
| `main.tex` §5 Experimental Setup | "162 per small tenant, 201 for ZAI" |
| `experiments_results.tex` §5.2.3 Scenario-Level Analysis | "41-user dense network … 165 users, 1,956 edges" |

The network statistics (density 0.196, diameter 3, 1,956 edges) from §5.2.3 are already tabulated in Table `tab:network_metrics` in §4.5. **Fix:** §5.2.3 should cite the table rather than restate the numbers inline.

---

### R8 — EABench "four contributions" listed three times

1. **Abstract** — four contributions enumerated (First/Second/Third/Fourth)
2. **Introduction** §1 (~line 214) — same four contributions re-enumerated ("The first contribution … The second … The third … The fourth …")
3. **Conclusion** §6 — "it joins four ingredients in a single platform"

The abstract→intro repetition is standard but the phrase structures are currently so close in length that they read as copy-paste. **Fix:** Abstract should be telegraphic (one sentence per contribution). Introduction should expand each contribution with a sentence of context. Conclusion should not re-enumerate but instead synthesize.

---

### R9 — Researcher architecture described in three places

1. `methodology_agent_runtime.tex` §3.2.2: "Under the researcher strategy, the runtime first invokes a planner to produce a structured plan and then executes that plan with the normal tool-enabled loop."
2. `experiments_results.tex` §5.1.1: full paragraph describing the four planning-prompt capabilities
3. `experiments_results.tex` §5.2.1: "Before issuing any tool call, Researcher prompts GPT-4o-mini to produce a structured research plan that decomposes the query into a dependency chain…"

**Fix:** §3.2.2 (methodology) describes the mechanism. §5.1.1 should state only which configuration was used. §5.2.1 should cite §3.2.2 for the mechanism and focus on the empirical explanation of observed results.

---

### R10 — Interactive debugging surfaces described twice

1. `methodology_interactive.tex` §3.6.2 Debugging Facilities: full paragraph listing four sidebar views (Chat, Evaluation, Side-by-Side, Data Generator) with explanations
2. Table `tab:debug_surfaces`: the same six surfaces in tabular form

The table adds no information beyond the paragraph. **Fix:** Either keep the table and shorten the paragraph to a one-sentence pointer, or drop the table and keep the paragraph.

---

## 3. Internal Inconsistencies

### I1 — "Four LLM calls" vs. "three judge prompts"

**Location A** — `main.tex` §5 Experimental Setup:
> "The automated judge is GPT-4o, evaluating each case via **four separate LLM calls**"

**Location B** — `experiments_results.tex` §5.1.2:
> "three judge prompts that together score correctness, retrieval quality, and citation grounding"

**Location C** — `experiments_results.tex` §5.2.5 Cost-Effectiveness:
> "Judge evaluation contributes **four additional LLM calls** per case: assertion check (one call **per assertion**), tool-search relevance, response-citation quality, and side-by-side comparison."

There are three distinct prompts (assertion_check, citation_relevance, response_citation), but assertion_check is called once *per assertion* (not once per case), and side-by-side comparison is only for comparative studies (not standard evaluation). The "four calls" claim in the setup section is therefore doubly wrong: the real count is (number of assertions + 2) for standard evaluation, not four. **Fix:** Correct `main.tex` §5 setup to say "one judge call per gold assertion plus two additional calls per case"; remove the side-by-side call from the standard-evaluation count.

---

### I2 — Temperature still appears in runtime YAML listing

`methodology_agent_runtime.tex` Figure `lst:runtime_yaml` (code listing) still shows:
```yaml
parameters: {temperature: 0.7}
```
Temperature was removed from all prose and tables per earlier revision, but the YAML listing—which is shown as a canonical configuration example—still contains it. This creates a contradiction: readers see temperature mentioned in the framework's own config schema even though the text no longer discusses it. **Fix:** Either remove the temperature line from the listing or add a note explaining it is an optional parameter not used in the experiments.

---

### I3 — Abstract claims evaluation harness is configurable with "thresholds"; code is hardcoded

**Abstract:**
> "The evaluation harness is likewise configurable, allowing researchers to redefine judge prompts and scoring thresholds without code changes."

**Actual code** (`python/src/eval/evaluator.py`): thresholds (0.75, 0.7) are hardcoded; only judge prompts are YAML-configurable.

This was flagged in the original metric audit but the abstract still claims threshold configurability. **Fix:** Abstract should say "redefine judge prompts" only; threshold configurability should be framed as a planned extension.

---

### I4 — Figure `fig:eval_harness` caption references nonexistent "response clarity" track

`methodology_eval_harness.tex` Figure caption (the LLM-as-a-judge figure): The code listing in the figure body (commented-out placeholder) described three tracks including "Response Clarity Score." The actual harness has two judge tracks (TS-Rel and RC-Rel) plus assertion check—no "response clarity" metric exists in the code or the metric table. The current figure caption was updated, but the *commented-out placeholder description inside the figure environment* still mentions "Track 3 (right, teal) — Response Clarity Score." **Fix:** Remove or update the commented placeholder text inside the figure environment.

---

### I5 — Scenario-level analysis cites `tab:iet_summary` for ZAI burstiness but the table is in a different section with no cross-section anchor

`experiments_results.tex` §5.2.3:
> "highest chat burstiness ($B = 0.66$, Table~\ref{tab:iet_summary})"

`tab:iet_summary` is in §4.5 (Dataset Statistics). The cross-reference is valid but the inline value ($B = 0.66$) differs slightly from the table value for "ZAI / Chat (1:1)" ($B = +0.658$). **Fix:** Use the table value precisely ($B = 0.658$) or round consistently.

---

### I6 — Assertion weight field declared but unused (mentioned in placeholder C3)

`methodology_eval_dataset.tex` §3.4.3:
> "They are written in natural language, may be **weighted by importance**"

The actual evaluator (`python/src/eval/evaluator.py`) ignores weights and computes a simple pass fraction. The assertion weight field is populated by the generator but has no effect on scoring. This is inconsistent with the methodology description. **Fix:** Either implement weighted scoring or change the methodology text to say weights are recorded for future use but scoring is currently unweighted.

---

### I7 — Researcher "Planner" model role inconsistently described

**Location A** — `main.tex` §5 setup:
> "the Researcher agent uses GPT-4o-mini **for both planning and execution**"

**Location B** — `experiments_results.tex` Table `tab:agent_configs`:
> Planning Model column: "GPT-4o-mini"

**Location C** — `experiments_results.tex` §5.1.1:
> "GPT-4o-mini first generates a structured … plan … The same GPT-4o-mini model then executes…"

These are consistent. However, **Table `tab:agent_configs` caption** says "'Planning model' refers to the LLM used for the optional pre-execution planning step"—implying execution might use a *different* model. The table entry "GPT-4o-mini" alone does not clarify that the same model is used for both stages. **Fix:** Add "(both planning and execution)" to the Researcher's Planning Model cell, or update the caption to say "Planning Model (execution model is identical unless otherwise noted)."

---

## 4. Structural Redundancy

### S1 — §3.1 architecture table and §3.1 prose describe the same pipeline

`methodology_overview.tex` Table `tab:pipeline_artifacts` lists six stages (Scenario specification, Tenant generation, Evaluation dataset generation, Agent runtime, Evaluation harness, Interactive debugging) with artifact and role columns. The surrounding prose in §3.1 describes the same six stages in paragraph form. The table adds column structure but repeats the same facts. **Fix:** The prose should narrate the pipeline flow; the table should contain only the artifact names and their roles without restating what the prose says.

---

### S2 — Five-stage generation pipeline described twice

`methodology_data_generation.tex` has both:
1. §3.3.2 Five-Stage Generation Pipeline — prose description of the five stages
2. Table `tab:generation_pipeline` — the same five stages in tabular form

Both contain nearly identical content (scaffold, user generation, daily narrative, artifact materialization, log export). **Fix:** Table should be the canonical reference. Prose should serve as narrative glue (entry conditions, design rationale) and cross-reference the table for stage-by-stage details.

---

### S3 — Metrics table (`tab:eval_metrics`) largely repeats the `itemize` list above it

`methodology_eval_harness.tex` §3.5.2 contains:
- An `itemize` list with four judge-based metric descriptions
- Immediately followed by Table `tab:eval_metrics` with the same seven metrics in tabular form

The itemize list and the table cover identical ground. **Fix:** Drop the itemize list and rely on the table; or drop the table and rely on the itemize list and the more-detailed §5.1.2 definitions.

---

### S4 — Two figures show pass rate and assertion score separately when one heatmap covers both

Figures `fig:pass_rate` and `fig:assertion_score` each show a single-metric bar chart. Figure `fig:metrics_heatmap` already shows all metrics across all nine agent–tenant cells. The two single-metric figures add little beyond what the heatmap shows. **Fix:** Remove `fig:pass_rate` and `fig:assertion_score`; cite `fig:metrics_heatmap` in the narrative instead.

---

### S5 — Two cost figures (`fig:latency_vs_pass` and `fig:cost_frontier`) cover overlapping content

`fig:latency_vs_pass` plots latency vs. pass rate; `fig:cost_frontier` plots prompt tokens vs. citation score. Both figures are described in §5.2.5 Cost-Effectiveness. All three data points (three agents) are the same; the narrative in §5.2.5 doesn't use the two figures to make distinct arguments. **Fix:** Merge into a single two-panel figure, or keep only the figure whose axes are directly discussed in the section argument.

---

## 5. Minor Wording Inconsistencies

| # | Location | Issue |
|---|---|---|
| W1 | Abstract vs. Introduction | "hot-swappable without code changes" (abstract) vs. "hot-swappable via declarative YAML files without source-code edits" (intro) — near-verbatim; one should differ |
| W2 | `scenarios_datasets.tex` §4.4 | Generation pipeline rederscribed in prose ("(i) a daily story prompt … (ii) summary prompts … (iii) content prompts") — duplicates §3.3 content; should be a cross-reference |
| W3 | `experiments_results.tex` §5.2.3 | "40-user dense network" should say "41-user" (Bertrand has 41 users per Table `tab:dataset_summary`) |
| W4 | `methodology_eval_harness.tex` §3.5.1 | YAML listing still shows `temperature: 0.0` under `parameters`; inconsistent with temperature removal from prose and tables |
| W5 | `experiments_results.tex` §5.2.4 | "Query types are assigned by the generator at case-creation time and recorded in the `query_type` field of the evaluation JSON; the reported split is derived from that field rather than from any post-hoc classification." — this procedural note belongs in §3.4, not in the results section |
