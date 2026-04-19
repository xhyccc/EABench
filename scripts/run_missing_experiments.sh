#!/usr/bin/env bash
# Orchestrates the missing experiments listed in
# EABench_paper/missing_experiments_plan.md.
#
# Usage:
#   bash scripts/run_missing_experiments.sh p0        # C4 + C6 + B8 (no LLM calls)
#   bash scripts/run_missing_experiments.sh c3        # ReAct-v3 ablation
#   bash scripts/run_missing_experiments.sh c5        # retrieval-only baseline
#   bash scripts/run_missing_experiments.sh c1        # GLM re-judge
#   bash scripts/run_missing_experiments.sh c2        # sample for annotation
#   bash scripts/run_missing_experiments.sh all       # p0 + c3 + c5 + c1 + c2

set -euo pipefail

# ---- repo layout ----------------------------------------------------------
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PY=".venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

# ---- env ------------------------------------------------------------------
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

# ---- agent / tenant matrix ------------------------------------------------
TENANTS=(
  "examples/tenants/bertrand-and-co.-20260407"
  "examples/tenants/staff-office-the-university-of-cambford-20260407"
  "examples/tenants/zai-intelligence-20260408"
)

eval_file_for() {
  # Return newest eval_dataset_*.yaml under a tenant dir.
  ls -1 "$1"/eval_dataset_*.yaml 2>/dev/null | sort | tail -n 1
}

run_agent_on_all_tenants() {
  local agent_yaml="$1"
  local tag="$2"                    # short tag used in result filename
  for t in "${TENANTS[@]}"; do
    local ev; ev="$(eval_file_for "$t")"
    [[ -z "$ev" ]] && { echo "  skip (no eval dataset): $t"; continue; }
    local tenant_yaml="$t/tenant.yaml"
    local tenant_id; tenant_id="$(basename "$t")"
    local ts; ts="$(date -u +%Y%m%d_%H%M%S)"
    local out="python/results/eval_${tenant_id}_${tag}_${ts}.json"
    echo "  >>> $tag on $tenant_id"
    ( cd python && "$REPO/$PY" run_eval.py \
        --tenant "$REPO/$tenant_yaml" \
        --eval   "$REPO/$ev" \
        --agent  "$REPO/$agent_yaml" \
        --judge  "$REPO/examples/evals/default_judge.yaml" \
        --output "$REPO/$out" )
    echo "  done -> $out"
  done
}

# ---- P0: analyses on existing data (zero cost) ----------------------------
phase_p0() {
  echo "=== P0: post-hoc analyses (C4 + C6 + B8) ==="
  "$PY" scripts/analyze_post_hoc.py --mode all
}

# ---- C3: ReAct-v3 ablation (gpt-4o-mini + T=0 + ReAct loop) ----------------
phase_c3() {
  echo "=== C3: ReAct-v3 ablation ==="
  run_agent_on_all_tenants "examples/agents/react_agent_v3.yaml" "react_v3"
}

# ---- C5: retrieval-only baseline ------------------------------------------
phase_c5() {
  echo "=== C5: retrieval-only baseline ==="
  run_agent_on_all_tenants "examples/agents/retrieval_baseline.yaml" "baseline"
}

# ---- C1: cross-model judge (GLM-4.7-FlashX via Zhipu) ---------------------
phase_c1() {
  echo "=== C1: re-judge ReAct-v1 + Researcher with GLM ==="
  if [[ -z "${OPENAI_API_KEY:-}" || -z "${OPENAI_API_BASE:-}" ]]; then
    echo "  OPENAI_API_KEY / OPENAI_API_BASE missing — skipping C1."
    return
  fi
  # Re-judge the latest results for react_v1 and researcher on all three tenants.
  for tag in react_v1 researcher; do
    for t in "${TENANTS[@]}"; do
      local tenant_id; tenant_id="$(basename "$t")"
      local src; src="$(ls -1 python/results/eval_${tenant_id}_${tag}_*.json 2>/dev/null | sort | tail -n 1 || true)"
      if [[ -z "$src" ]]; then
        # Fall back to any file for this tenant (older filenames lacked the tag).
        src="$(ls -1 python/results/eval_${tenant_id}_*.json 2>/dev/null | sort | tail -n 1 || true)"
      fi
      [[ -z "$src" ]] && { echo "  skip (no source): $tenant_id / $tag"; continue; }
      echo "  >>> glm-judge $src"
      "$PY" scripts/rejudge_with_glm.py \
          --input "$src" \
          --judge examples/evals/glm_judge.yaml
    done
  done
}

# ---- C2: stratified sample for human annotation ---------------------------
phase_c2() {
  echo "=== C2: stratified sample for annotation ==="
  "$PY" scripts/analyze_post_hoc.py --mode sample-for-annotation \
      --tenant bertrand-and-co.-20260407 --per-type 50
}

case "${1:-}" in
  p0)   phase_p0 ;;
  c3)   phase_c3 ;;
  c5)   phase_c5 ;;
  c1)   phase_c1 ;;
  c2)   phase_c2 ;;
  all)  phase_p0; phase_c5; phase_c3; phase_c1; phase_c2 ;;
  *)
    cat <<EOF
Usage: $0 {p0|c3|c5|c1|c2|all}

  p0  Zero-cost analyses on existing JSON (C4 CI, C6 threshold, B8 cost)
  c3  Run ReAct-v3 ablation across 3 tenants (~\$18)
  c5  Run retrieval-only baseline across 3 tenants (~\$6)
  c1  Re-judge existing ReAct-v1/Researcher results with GLM-4.7-FlashX
  c2  Produce CSV sample for human annotation (no LLM)
  all Run everything in dependency order (p0 first, then c5, c3, c1, c2)
EOF
    exit 1
    ;;
esac
