#!/usr/bin/env python3
"""
C1 — Cross-model judge. Re-judge EXISTING agent trajectories with
GLM-4.7-FlashX (Zhipu AI) via its OpenAI-compatible endpoint.

Reads a results JSON produced by run_eval.py, loads the GLM judge config,
invokes the chat-completions endpoint for each case (assertion_check,
citation_relevance, response_citation), and writes a new JSON alongside
with suffix `_glmjudge.json`.

Requires: OPENAI_API_KEY + OPENAI_API_BASE in .env (already set for GLM),
and `pip install openai` (already in python/requirements.txt).

Usage:
    python scripts/rejudge_with_glm.py \
        --input  python/results/eval_bertrand-and-co.-20260407_react_v1_20260410_062403.json \
        --judge  examples/evals/glm_judge.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

try:
    from openai import OpenAI  # type: ignore
except ImportError:
    OpenAI = None


def extract_yaml_block(text: str) -> dict:
    """Primary: YAML parse. Best-effort for GLM which tends to emit
    unquoted explanation strings containing apostrophes/colons that break
    strict YAML."""
    m = re.search(r"```yaml\s*(.*?)```", text, re.DOTALL)
    payload = m.group(1) if m else text
    try:
        parsed = yaml.safe_load(payload)
        if isinstance(parsed, dict):
            return parsed
    except yaml.YAMLError:
        pass
    return {}


def extract_score(text: str) -> float:
    """Regex fallback: match `score: <number>` anywhere in the output."""
    m = re.search(r"score\s*:\s*([0-9]*\.?[0-9]+)", text)
    if not m:
        return 0.0
    try:
        v = float(m.group(1))
        return max(0.0, min(1.0, v))
    except ValueError:
        return 0.0


def extract_assertion_satisfied(text: str) -> list[int]:
    """Regex fallback: capture every `satisfied: 0|1` occurrence in order."""
    return [int(x) for x in re.findall(r"satisfied\s*:\s*([01])", text)]


def make_client(judge_cfg: dict) -> "OpenAI":
    base_url = (
        judge_cfg.get("model", {}).get("base_url")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("OPENAI_BASE_URL")
    )
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("ERROR: OPENAI_API_KEY not set (needed for GLM endpoint)")
    return OpenAI(api_key=api_key, base_url=base_url)


def call_glm(client, model: str, prompt: str, temperature: float = 0.0) -> str:
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


def _extract_assertion_texts(case: dict) -> list[str]:
    """Support both the run_eval.py output schema (assertion_results with
    `description`) and the older eval-dataset schema (`assertions` list)."""
    ar = case.get("assertion_results") or []
    if ar:
        return [a.get("description") or a.get("text") or "" for a in ar]
    raw = case.get("assertions") or []
    return [a if isinstance(a, str) else a.get("text", "") for a in raw]


def _extract_cited_artifacts(case: dict) -> list[str]:
    """Cited artifact IDs are not stored directly; derive from tool_calls."""
    ids: list[str] = []
    for tc in case.get("tool_calls") or []:
        result = tc.get("result") or tc.get("output") or {}
        if isinstance(result, dict):
            for item in (result.get("results") or result.get("items") or []):
                if isinstance(item, dict):
                    aid = item.get("id") or item.get("artifact_id")
                    if aid:
                        ids.append(str(aid))
    # De-duplicate while preserving order.
    seen: set[str] = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def rejudge_case(client, judge_cfg: dict, case: dict) -> dict:
    model = judge_cfg["model"]["name"]
    temperature = judge_cfg["model"].get("parameters", {}).get("temperature", 0.0)
    prompts = judge_cfg["prompts"]
    query = case.get("query", "")
    response = case.get("response", "")
    tool_calls = json.dumps(case.get("tool_calls", []), indent=2)[:8000]
    cited = ", ".join(_extract_cited_artifacts(case))

    out = {"case_id": case["case_id"]}

    # 1. assertion_check -------------------------------------------------
    assertions = _extract_assertion_texts(case)
    if assertions:
        assertion_list = "\n".join(
            f"- id: a{i}\n  text: {t}" for i, t in enumerate(assertions) if t
        )
        p = prompts["assertion_check"].format(
            query=query, response=response, assertions=assertion_list,
        )
        raw = call_glm(client, model, p, temperature)
        parsed = extract_yaml_block(raw)
        sats = [int(r.get("satisfied", 0)) for r in parsed.get("results", []) or []]
        if not sats:  # YAML parse failed — fall back to regex.
            sats = extract_assertion_satisfied(raw)
        out["assertion_score_glm"] = sum(sats) / len(sats) if sats else 0.0

    # 2. citation_relevance (TS-Rel) ------------------------------------
    p = prompts["citation_relevance"].format(
        query=query, response=response, tool_calls=tool_calls,
    )
    raw = call_glm(client, model, p, temperature)
    parsed = extract_yaml_block(raw)
    out["ts_rel_glm"] = float(parsed.get("score", 0.0) or 0.0) if parsed else extract_score(raw)

    # 3. response_citation (RC-Rel) -------------------------------------
    p = prompts["response_citation"].format(
        query=query, response=response, cited_artifacts=cited,
    )
    raw = call_glm(client, model, p, temperature)
    parsed = extract_yaml_block(raw)
    out["rc_rel_glm"] = float(parsed.get("score", 0.0) or 0.0) if parsed else extract_score(raw)

    # Pass gate: assertion score only (rc_rel omitted — artifact extraction
    # from tool_call schemas is unreliable across agents, making rc_rel a
    # noisy signal unsuitable for cross-model comparison).
    out["passed_glm"] = out.get("assertion_score_glm", 0.0) >= 0.75
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to existing eval JSON")
    ap.add_argument("--judge", default="examples/evals/glm_judge.yaml")
    ap.add_argument("--limit", type=int, default=0,
                    help="Max cases to re-judge (0 = all)")
    args = ap.parse_args()

    if OpenAI is None:
        sys.exit("ERROR: pip install openai")

    judge_cfg = yaml.safe_load(Path(args.judge).read_text())
    client = make_client(judge_cfg)

    doc = json.loads(Path(args.input).read_text())
    cases = doc.get("cases", [])
    if args.limit:
        cases = cases[: args.limit]

    out_cases = []
    for i, c in enumerate(cases, 1):
        try:
            res = rejudge_case(client, judge_cfg, c)
        except Exception as exc:  # noqa: BLE001
            res = {"case_id": c.get("case_id"), "error": str(exc)}
        out_cases.append(res)
        if i % 10 == 0:
            print(f"  [{i}/{len(cases)}] done")

    out_path = Path(args.input).with_name(Path(args.input).stem + "_glmjudge.json")
    passed_glm = sum(1 for r in out_cases if r.get("passed_glm"))
    out = {
        "source": args.input,
        "judge": args.judge,
        "judge_model": judge_cfg["model"]["name"],
        "total": len(out_cases),
        "passed_glm": passed_glm,
        "pass_rate_glm": round(passed_glm / len(out_cases), 4) if out_cases else 0.0,
        "cases": out_cases,
    }
    out_path.write_text(json.dumps(out, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
