import asyncio
import re
import yaml
import textwrap
import time
from typing import List, Dict, Any, Tuple
from scipy import stats
from .models import EvaluationCase, EvaluationResult, EvaluationSet, ComparisonResult
from ..core.agent_runner import AgentRunner
from ..core.llm_provider import LLMProvider
from ..core.search_engine import SearchEngine
from ..sandbox.base import SandboxInterface

class Evaluator:
    def __init__(self, runner: AgentRunner, llm: LLMProvider, sandbox: SandboxInterface, search_engine: SearchEngine, prompts: Dict[str, str] = None):
        self.runner = runner
        self.judge_llm = llm # Use the same LLM for judging for now, or could be separate
        self.sandbox = sandbox
        self.search_engine = search_engine
        self.prompts = prompts or {}

    async def evaluate_batch(self, eval_set: EvaluationSet) -> List[EvaluationResult]:
        results = []
        for case in eval_set.cases:
            result = await self.evaluate_single(case)
            results.append(result)
        return results

    def calculate_p_value(self, scores_a: List[float], scores_b: List[float]) -> float:
        """Calculates the p-value using a paired t-test for two sets of scores."""
        try:
            if len(scores_a) != len(scores_b) or len(scores_a) < 2:
                return None
            
            # Check if scores are identical
            if scores_a == scores_b:
                return 1.0
                
            t_stat, p_val = stats.ttest_rel(scores_a, scores_b)
            return p_val
        except Exception as e:
            print(f"Error calculating p-value: {e}")
            return None

    async def compare_two(self, case: EvaluationCase, result_a: EvaluationResult, result_b: EvaluationResult) -> ComparisonResult:
        # Format assertions
        assertions_list = []
        for i, a in enumerate(case.assertions):
            assertions_list.append(f"{i+1}. {a.description}")
        assertions_text = "\n".join(assertions_list)

        prompt_template = self.prompts.get("side_by_side", "")
        if not prompt_template:
             return ComparisonResult(
                case_id=case.id,
                query=case.query,
                result_a=result_a,
                result_b=result_b,
                winner="Tie",
                reasoning="Missing side_by_side prompt configuration.",
                score=0.0
            )

        prompt = prompt_template.format(
            query=case.query,
            response_a=result_a.response,
            response_b=result_b.response,
            assertions=assertions_text
        )

        messages = [{"role": "user", "content": prompt}]
        try:
            judgment = await self.judge_llm.get_completion(messages)
            data = self._parse_yaml_response(judgment)
            
            return ComparisonResult(
                case_id=case.id,
                query=case.query,
                result_a=result_a,
                result_b=result_b,
                winner=data.get("winner", "Tie"),
                reasoning=data.get("reasoning", "No reasoning provided."),
                score=float(data.get("better_response_score", 0.0))
            )
        except Exception as e:
            return ComparisonResult(
                case_id=case.id,
                query=case.query,
                result_a=result_a,
                result_b=result_b,
                winner="Tie",
                reasoning=f"Error in comparison: {e}",
                score=0.0
            )

    async def evaluate_single(self, case: EvaluationCase) -> EvaluationResult:
        # 1. Run the Agent
        print(f"Running case: {case.query}")
        
        # Set User Context if provided
        if case.user_id:
            self.search_engine.set_user_context(case.user_id)

        # Reset runner history for clean slate? Or keep context? 
        # Usually eval cases are independent.
        self.runner.history = [] 
        
        start_time = time.time()
        run_metrics = {}
        try:
            run_result = await self.runner.run(case.query, self.sandbox, self.search_engine)
            response_text = run_result.response
            run_metrics = run_result.metrics
            
            # Extract tool calls from history
            tool_calls = []
            for msg in self.runner.history:
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls.append({"name": tc.name, "arguments": tc.arguments})
        except Exception as e:
            response_text = f"Error: {str(e)}"
            tool_calls = []
        
        end_time = time.time()
        latency = end_time - start_time

        # 2. Evaluate: Citation Relevance
        citation_score, citation_reason = await self._evaluate_citation(case.query, tool_calls, response_text)

        # 3. Evaluate: Assertions
        assertion_score, assertion_reason, assertion_results = await self._evaluate_assertions(case.query, response_text, case.assertions)

        # 4. Aggregate
        passed = assertion_score >= 0.75 and citation_score >= 0.7 # Thresholds
        
        metrics = {
            "citation_score": citation_score,
            "assertion_score": assertion_score,
            "latency": latency,
            **run_metrics
        }

        return EvaluationResult(
            case_id=case.id,
            query=case.query,
            response=response_text,
            tool_calls=tool_calls,
            metrics=metrics,
            assertion_results=assertion_results,
            reasoning=f"Citation: {citation_reason}\nAssertions: {assertion_reason}",
            passed=passed
        )

    def _parse_yaml_response(self, response_text: str) -> Dict[str, Any]:
        try:
            # Find code block
            pattern = r"```(?:yaml)?(.*?)```"
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                clean_text = match.group(1)
            else:
                # Fallback: assume the whole text is YAML if no block found
                clean_text = response_text
            
            # Dedent to handle indentation issues
            clean_text = textwrap.dedent(clean_text)
            
            return yaml.safe_load(clean_text.strip())
        except Exception as e:
            print(f"Error parsing YAML: {e}")
            return {}

    async def _evaluate_citation(self, query: str, tool_calls: List[Dict], response: str) -> Tuple[float, str]:
        prompt = self.prompts["citation_relevance"].format(
            query=query,
            tool_calls=str(tool_calls),
            response=response
        )
        
        # Call LLM
        messages = [{"role": "user", "content": prompt}]
        try:
            judgment = await self.judge_llm.get_completion(messages)
            
            # Parse YAML Score
            data = self._parse_yaml_response(judgment)
            score = float(data.get("score", 0.0))
            explanation = data.get("explanation", "No explanation provided.")
            
            return score, explanation
        except Exception as e:
            return 0.0, f"Error in judgment: {e}"

    async def _evaluate_assertions(self, query: str, response: str, assertions: List[Any]) -> Tuple[float, str, List[Dict[str, Any]]]:
        # Format assertions with IDs
        assertions_list = []
        for i, a in enumerate(assertions):
            assertions_list.append(f"{i+1}. {a.description}")
        assertions_text = "\n".join(assertions_list)

        prompt = self.prompts["assertion_check"].format(
            query=query,
            response=response,
            assertions=assertions_text
        )
        
        messages = [{"role": "user", "content": prompt}]
        try:
            judgment = await self.judge_llm.get_completion(messages)
            
            # Parse YAML Score
            data = self._parse_yaml_response(judgment)
            # score = float(data.get("final_score", 0.0))
            summary = data.get("summary", "No summary provided.")
            assertion_results = data.get("assertions", [])
            
            # Calculate Pass Rate
            passed_count = sum(1 for r in assertion_results if r.get('passed', False))
            total_count = len(assertions)
            score = passed_count / total_count if total_count > 0 else 0.0
            
            # Enrich with descriptions
            for res in assertion_results:
                try:
                    idx = int(res.get('id', 0)) - 1
                    if 0 <= idx < len(assertions):
                        res['description'] = assertions[idx].description
                except Exception:
                    pass
            
            return score, summary, assertion_results
        except Exception as e:
            return 0.0, f"Error in judgment: {e}", []
