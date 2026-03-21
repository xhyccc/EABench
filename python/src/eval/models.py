from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class Assertion(BaseModel):
    description: str
    weight: float = 1.0

class EvaluationCase(BaseModel):
    id: str
    query: str
    user_id: Optional[str] = None
    assertions: List[Assertion]
    expected_tools: Optional[List[str]] = None # Optional: check if specific tools were used

class EvaluationResult(BaseModel):
    case_id: str
    query: str
    response: str
    tool_calls: List[Dict[str, Any]]
    metrics: Dict[str, Any] # e.g., {"assertion_score": 0.8, "citation_score": 1.0}
    assertion_results: Optional[List[Dict[str, Any]]] = None
    reasoning: str
    passed: bool

class EvaluationSet(BaseModel):
    name: str
    description: str
    cases: List[EvaluationCase]

class ComparisonResult(BaseModel):
    case_id: str
    query: str
    result_a: EvaluationResult
    result_b: EvaluationResult
    winner: str # "A", "B", "Tie"
    reasoning: str
    score: float
