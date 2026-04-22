# Revision Implementation Plan (v3)

1. **Set editorial policy first (30 min)**
- Goal: align all sections to one claim scope: "single-judge results with bounded conclusions."
- Apply globally in `EABench_paper/main.tex`: soften any universal/causal wording to conditional wording.
- Acceptance check:
  - No sentence implies completed cross-judge robustness unless evidence is shown.
  - No sentence promises human validation unless a subsection reports it.

2. **Remove redundancy in front matter (1.5-2 hrs)**
- Edit `EABench_paper/main.tex` around Introduction and roadmap paragraphs.
- Actions:
  - Keep the full "three recurring gaps" narrative only once in Introduction.
  - Compress Abstract contribution bullets to one sentence each.
  - Remove repeated platform-component enumeration from roadmap paragraph.
- Acceptance check:
  - "three recurring gaps" explained once in detail, referenced briefly elsewhere.
  - Intro word count reduced without losing any unique claim.

3. **Fix claim-evidence inconsistencies (1.5 hrs)**
- Edit cross-model framing in `EABench_paper/main.tex` (cross-model subsection).
- Actions:
  - Keep cross-model protocol as framework capability, but explicitly state current paper reports primarily single-judge results.
  - Reframe GLM parser failure as limitation and remove any implied robustness conclusion.
  - Resolve "human validation" mismatch by either:
    - adding a small reported subsection, or
    - deleting that roadmap mention.
- Acceptance check:
  - No contradiction between protocol claims and executed evidence.

4. **Enforce section-function discipline (2-3 hrs)**
- Related Work cleanup in `EABench_paper/main.tex`:
  - Keep comparative synthesis.
  - Remove promotional/duplicate "configurable platform" language already in Intro/Method.
- Method section boundary:
  - Keep implementation and design choices only.
  - Move interpretive statements to Experiments/Discussion if needed.
- Discussion sharpening:
  - Keep one canonical scenario-specific takeaway, remove paraphrase repeats.
- Acceptance check:
  - Related Work does not restate contributions.
  - Method does not argue results.
  - Discussion does not re-list setup.

5. **Add compact threats-to-validity summary (45 min)**
- Place at end of Experiments before conclusion in `EABench_paper/main.tex`.
- Include:
  - single-judge dependence,
  - parser fragility for alternate judge,
  - synthetic realism constraints,
  - which conclusions remain robust.
- Acceptance check:
  - Every major headline claim in Abstract has a matching caveat path in threats or results.

6. **Final coherence and traceability pass (1 hr)**
- Do a targeted grep pass for repeated motifs:
  - "three recurring gaps"
  - "four agent configurations"
  - "scenario-specific"
  - "cross-model evaluation"
- Ensure each appears in one primary location plus short references only.
- Acceptance check:
  - No repeated paragraph-level content across Abstract/Intro/Discussion.
  - Abstract claims directly trace to results/limitations.

7. **Optional execution order for fastest win**
- First: inconsistency fixes (Step 3), because they affect scientific validity.
- Second: redundancy cuts (Step 2 + Step 4), because they improve reviewer perception.
- Third: threats box + final pass (Step 5 + Step 6).

---

## Definition of Done
1. No roadmap promise without delivered evidence.
2. No strong causal/general claims unsupported by robustness protocol.
3. Repetition reduced across Abstract, Introduction, and Discussion.
4. Reader can identify one canonical statement each for:
- problem gap,
- platform contribution,
- empirical takeaway,
- limitations.
