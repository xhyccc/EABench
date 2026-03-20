use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Assertion
// ---------------------------------------------------------------------------

/// A single evaluation assertion.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Assertion {
    pub description: String,
    #[serde(default = "default_weight")]
    pub weight: f64,
}

fn default_weight() -> f64 {
    1.0
}

impl Assertion {
    pub fn new(description: impl Into<String>) -> Self {
        Assertion {
            description: description.into(),
            weight: 1.0,
        }
    }
}

// ---------------------------------------------------------------------------
// EvaluationCase
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct EvaluationCase {
    pub id: String,
    pub query: String,
    pub user_id: Option<String>,
    pub assertions: Vec<Assertion>,
    pub expected_tools: Option<Vec<String>>,
}

// ---------------------------------------------------------------------------
// EvaluationResult
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct EvaluationResult {
    pub case_id: String,
    pub query: String,
    pub response: String,
    pub tool_calls: Vec<String>,
    pub metrics: HashMap<String, f64>,
    pub assertion_results: Vec<HashMap<String, String>>,
    pub reasoning: String,
    pub passed: bool,
}

// ---------------------------------------------------------------------------
// EvaluationSet
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct EvaluationSet {
    pub name: String,
    pub description: String,
    pub cases: Vec<EvaluationCase>,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_assertion_default_weight() {
        let a = Assertion::new("file exists");
        assert!((a.weight - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_assertion_description() {
        let a = Assertion::new("response mentions budget");
        assert_eq!(a.description, "response mentions budget");
    }

    #[test]
    fn test_evaluation_case_construction() {
        let case = EvaluationCase {
            id: "c1".to_string(),
            query: "What is the budget?".to_string(),
            user_id: None,
            assertions: vec![Assertion::new("mentions budget")],
            expected_tools: None,
        };
        assert_eq!(case.id, "c1");
        assert_eq!(case.assertions.len(), 1);
    }

    #[test]
    fn test_evaluation_result_construction() {
        let mut metrics = HashMap::new();
        metrics.insert("assertion_score".to_string(), 1.0);
        let result = EvaluationResult {
            case_id: "c1".to_string(),
            query: "query".to_string(),
            response: "response".to_string(),
            tool_calls: vec![],
            metrics,
            assertion_results: vec![],
            reasoning: "passed".to_string(),
            passed: true,
        };
        assert!(result.passed);
        assert_eq!(*result.metrics.get("assertion_score").unwrap(), 1.0);
    }

    #[test]
    fn test_evaluation_set_construction() {
        let set = EvaluationSet {
            name: "Test Set".to_string(),
            description: "A set of tests".to_string(),
            cases: vec![EvaluationCase {
                id: "c1".to_string(),
                query: "q".to_string(),
                user_id: None,
                assertions: vec![],
                expected_tools: None,
            }],
        };
        assert_eq!(set.cases.len(), 1);
    }
}
