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
            pattern = r"```(?:yaml|json)?(.*?)```"
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

    def _fetch_entity_content(self, entity_type: str, entity_id: str) -> str:
        tenant = self.search_engine.tenant
        if not tenant:
            return None
            
        entity_type = entity_type.lower().strip()
        entity_id = entity_id.strip()
        
        if entity_type == 'email':
            for email in tenant.emails:
                if email.id == entity_id:
                    return f"Subject: {email.subject}\nBody: {email.body}"
        elif entity_type == 'file':
            # entity_id is the file path; sandbox provides path-traversal protection
            if not self.sandbox:
                return None
            try:
                return self.sandbox.read_file(entity_id)
            except (FileNotFoundError, ValueError, PermissionError, AttributeError):
                return None
        elif entity_type == 'chat':
            for chat in tenant.chats:
                if chat.id == entity_id:
                    return "\n".join([f"{m.from_user}: {m.content}" for m in chat.messages])
        elif entity_type in ['group_chat', 'group chat']:
             for gc in tenant.group_chats:
                if gc.id == entity_id:
                    return "\n".join([f"{m.from_user}: {m.content}" for m in gc.messages])
        elif entity_type == 'channel':
             for ch in tenant.channels:
                if ch.id == entity_id:
                    return "\n".join([f"{p.author}: {p.content}" for p in ch.posts])
        elif entity_type == 'meeting':
            for m in tenant.meetings:
                if m.id == entity_id:
                    content = f"Title: {m.title}\nAgenda: {m.agenda}"
                    if m.transcript:
                        content += f"\nTranscript: {m.transcript}"
                    return content
        
        return None

    async def _evaluate_citation(self, query: str, tool_calls: List[Dict], response: str) -> Tuple[float, str]:
        # Parse reference entries from the References section.
        # System-prompt format: - *Type*: <type> (ID: <id>)
        # e.g.  - *Type*: Email (ID: email_001)
        pattern = r"\*Type\*:\s+([^\n(]+?)\s+\(ID:\s+([^)\n]+?)\)"
        matches = re.findall(pattern, response)

        if not matches:
            return 0.0, "No structured citations found in the response."

        total_score = 0.0
        explanations = []

        for i, (cit_type, cit_id) in enumerate(matches, 1):
            cit_type = cit_type.strip()
            cit_id = cit_id.strip()
            content = self._fetch_entity_content(cit_type, cit_id)
            
            if not content:
                explanations.append(f"Citation {i} ({cit_type} ID: {cit_id}): Content not found (Hallucination).")
                continue
                
            # Evaluate relevance
            prompt = f"""
            You are an evaluator. Determine if the cited content is relevant to the user's query.
            
            User Query: {query}
            
            Cited Content ({cit_type}):
            {content[:3000]} 
            
            Task:
            1. Is this content relevant to answering the query?
            2. Assign a relevance score from 0.0 to 1.0.
            
            Output YAML:
            score: <float>
            reason: <string>
            """
            
            messages = [{"role": "user", "content": prompt}]
            try:
                judgment = await self.judge_llm.get_completion(messages)
                data = self._parse_yaml_response(judgment)
                score = float(data.get("score", 0.0))
                reason = data.get("reason", "No reason")
                
                total_score += score
                explanations.append(f"Citation {i}: {score} - {reason}")
            except Exception as e:
                explanations.append(f"Citation {i}: Error evaluating - {e}")
                
        final_score = total_score / len(matches) if matches else 0.0
        return final_score, "\n".join(explanations)

    async def _evaluate_assertions(self, query: str, response: str, assertions: List[Any]) -> Tuple[float, str, List[Dict[str, Any]]]:
        # Format assertions with IDs
        assertions_list = []
        for i, a in enumerate(assertions):
            assertions_list.append(f"{i+1}. {a.description}")
        assertions_text = "\n".join(assertions_list)

        prompt_template = self.prompts.get("assertion_check")
        if not prompt_template:
            return 0.0, "assertion_check prompt not configured.", []

        prompt = prompt_template.format(
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
            
            # Enrich with descriptions — catch only specific indexing/type errors
            for res in assertion_results:
                try:
                    idx = int(res.get('id', 0)) - 1
                    if 0 <= idx < len(assertions):
                        res['description'] = assertions[idx].description
                except (ValueError, TypeError, IndexError):
                    pass
            
            return score, summary, assertion_results
        except Exception as e:
            return 0.0, f"Error in judgment: {e}", []
