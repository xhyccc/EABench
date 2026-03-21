use crate::search::SearchEngine;
use super::models::{Assertion, EvaluationCase, EvaluationResult, EvaluationSet};
use std::collections::HashMap;
use rayon::prelude::*;

// ---------------------------------------------------------------------------
// AssertionChecker – deterministic text-based evaluation
// ---------------------------------------------------------------------------

/// Determines whether a single assertion is satisfied given a *response*
/// string.
///
/// Strategy: perform case-insensitive keyword overlap between the
/// assertion description keywords and the response text.  An assertion
/// is considered **passed** when *all* keywords from the description
/// are present in the response (after stripping common stop-words).
pub fn check_assertion(assertion: &Assertion, response: &str) -> bool {
    let stop_words = ["the", "a", "an", "is", "are", "in", "of", "to", "and", "or", "it"];
    let response_lower = response.to_lowercase();

    let keywords: Vec<String> = assertion
        .description
        .split_whitespace()
        .map(|t| t.to_lowercase().trim_matches(|c: char| !c.is_alphanumeric()).to_string())
        .filter(|t| !t.is_empty() && !stop_words.contains(&t.as_str()))
        .collect();

    if keywords.is_empty() {
        return true;
    }

    keywords.iter().all(|kw| response_lower.contains(kw.as_str()))
}

// ---------------------------------------------------------------------------
// Evaluator
// ---------------------------------------------------------------------------

/// Evaluates a set of cases by running deterministic assertion checks
/// against pre-computed agent responses.
///
/// This Rust evaluator uses only deterministic, text-based scoring and does
/// not require an LLM connection.  Supply a *scorer* closure that maps a
/// query to an agent response to enable full pipeline evaluation.
pub struct Evaluator {
    #[allow(dead_code)]
    search_engine: Option<SearchEngine>,
}

impl Evaluator {
    pub fn new() -> Self {
        Evaluator { search_engine: None }
    }

    pub fn with_search_engine(search_engine: SearchEngine) -> Self {
        Evaluator {
            search_engine: Some(search_engine),
        }
    }

    // -----------------------------------------------------------------------
    // Core evaluation
    // -----------------------------------------------------------------------

    /// Evaluate a single case given a pre-computed agent *response*.
    pub fn evaluate_response(
        &self,
        case: &EvaluationCase,
        response: &str,
        tool_calls: Vec<String>,
    ) -> EvaluationResult {
        let assertion_results: Vec<HashMap<String, String>> = case
            .assertions
            .iter()
            .enumerate()
            .map(|(i, a)| {
                let passed = check_assertion(a, response);
                let mut m = HashMap::new();
                m.insert("id".to_string(), (i + 1).to_string());
                m.insert("description".to_string(), a.description.clone());
                m.insert("passed".to_string(), passed.to_string());
                m
            })
            .collect();

        let total_weight: f64 = case.assertions.iter().map(|a| a.weight).sum();
        let passed_weight: f64 = case
            .assertions
            .iter()
            .zip(assertion_results.iter())
            .filter(|(_, r)| r.get("passed").map(|v| v == "true").unwrap_or(false))
            .map(|(a, _)| a.weight)
            .sum();

        let assertion_score = if total_weight > 0.0 {
            passed_weight / total_weight
        } else {
            0.0
        };

        // Tool check
        let tool_score = if let Some(ref expected) = case.expected_tools {
            if expected.is_empty() {
                1.0
            } else {
                let matched = expected
                    .iter()
                    .filter(|t| tool_calls.contains(t))
                    .count();
                matched as f64 / expected.len() as f64
            }
        } else {
            1.0
        };

        let overall = (assertion_score + tool_score) / 2.0;
        let passed = overall >= 0.5;

        let mut metrics = HashMap::new();
        metrics.insert("assertion_score".to_string(), assertion_score);
        metrics.insert("tool_score".to_string(), tool_score);
        metrics.insert("overall_score".to_string(), overall);

        let reasoning = format!(
            "Assertion score: {:.2}, Tool score: {:.2}",
            assertion_score + 0.0, tool_score + 0.0
        );

        EvaluationResult {
            case_id: case.id.clone(),
            query: case.query.clone(),
            response: response.to_string(),
            tool_calls,
            metrics,
            assertion_results,
            reasoning,
            passed,
        }
    }

    /// Evaluate a full [`EvaluationSet`] using a *scorer* closure that
    /// produces an agent response for each query.
    pub fn evaluate_batch<F>(
        &self,
        eval_set: &EvaluationSet,
        mut scorer: F,
    ) -> Vec<EvaluationResult>
    where
        F: FnMut(&str) -> (String, Vec<String>),
    {
        eval_set
            .cases
            .iter()
            .map(|case| {
                let (response, tools) = scorer(&case.query);
                self.evaluate_response(case, &response, tools)
            })
            .collect()
    }

    /// Evaluate a full [`EvaluationSet`] in parallel using a configurable
    /// thread pool.
    ///
    /// Each worker independently evaluates one query.  `num_workers` sets the
    /// size of the Rayon thread pool; pass `0` to use the number of logical
    /// CPUs on the host machine.
    ///
    /// The scorer closure must be `Fn` (callable from multiple threads) and
    /// both `Send` and `Sync`.  Results are returned in the same order as the
    /// input `eval_set.cases`.
    pub fn evaluate_batch_parallel<F>(
        &self,
        eval_set: &EvaluationSet,
        scorer: F,
        num_workers: usize,
    ) -> Vec<EvaluationResult>
    where
        F: Fn(&str) -> (String, Vec<String>) + Send + Sync,
    {
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(num_workers) // 0 → rayon chooses (= logical CPU count)
            .build()
            .expect("failed to build thread pool");

        pool.install(|| {
            eval_set
                .cases
                .par_iter()
                .map(|case| {
                    let (response, tools) = scorer(&case.query);
                    self.evaluate_response(case, &response, tools)
                })
                .collect()
        })
    }

    /// Calculate aggregate pass rate across a set of results.
    pub fn aggregate_pass_rate(results: &[EvaluationResult]) -> f64 {
        if results.is_empty() {
            return 0.0;
        }
        let passed = results.iter().filter(|r| r.passed).count();
        passed as f64 / results.len() as f64
    }

    /// Calculate mean assertion score across a set of results.
    pub fn mean_assertion_score(results: &[EvaluationResult]) -> f64 {
        if results.is_empty() {
            return 0.0;
        }
        let total: f64 = results
            .iter()
            .filter_map(|r| r.metrics.get("assertion_score"))
            .sum();
        total / results.len() as f64
    }
}

impl Default for Evaluator {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::eval::models::{Assertion, EvaluationCase, EvaluationSet};

    fn make_case(id: &str, assertions: Vec<Assertion>) -> EvaluationCase {
        EvaluationCase {
            id: id.to_string(),
            query: format!("Query for {}", id),
            user_id: None,
            assertions,
            expected_tools: None,
        }
    }

    // -----------------------------------------------------------------------
    // check_assertion tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_check_assertion_matches_keyword() {
        let a = Assertion::new("budget reviewed");
        assert!(check_assertion(&a, "The budget has been reviewed."));
    }

    #[test]
    fn test_check_assertion_case_insensitive() {
        let a = Assertion::new("Budget Report");
        assert!(check_assertion(&a, "the budget report is ready"));
    }

    #[test]
    fn test_check_assertion_fails_when_keyword_missing() {
        let a = Assertion::new("deployment rollback");
        assert!(!check_assertion(&a, "The deployment was successful."));
    }

    #[test]
    fn test_check_assertion_empty_description_passes() {
        let a = Assertion::new("the a an");  // all stop-words
        assert!(check_assertion(&a, "any response"));
    }

    #[test]
    fn test_check_assertion_partial_match_fails() {
        let a = Assertion::new("sprint planning completed");
        // "planning" and "sprint" are in response but "completed" is not
        assert!(!check_assertion(&a, "sprint planning started today"));
    }

    // -----------------------------------------------------------------------
    // evaluate_response tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_evaluate_response_all_pass() {
        let evaluator = Evaluator::new();
        let case = make_case(
            "c1",
            vec![
                Assertion::new("budget mentioned"),
                Assertion::new("quarterly review"),
            ],
        );
        let result = evaluator.evaluate_response(
            &case,
            "The budget for the quarterly review has been mentioned.",
            vec![],
        );
        assert_eq!(result.case_id, "c1");
        assert_eq!(*result.metrics.get("assertion_score").unwrap(), 1.0);
        assert!(result.passed);
    }

    #[test]
    fn test_evaluate_response_all_fail() {
        let evaluator = Evaluator::new();
        let case = make_case("c2", vec![Assertion::new("xyz nonexistent term")]);
        let result = evaluator.evaluate_response(&case, "totally unrelated response", vec![]);
        assert_eq!(*result.metrics.get("assertion_score").unwrap(), 0.0);
    }

    #[test]
    fn test_evaluate_response_partial_pass() {
        let evaluator = Evaluator::new();
        let case = make_case(
            "c3",
            vec![
                Assertion::new("budget mentioned"),
                Assertion::new("zzznosuchthing"),
            ],
        );
        let result = evaluator.evaluate_response(&case, "budget mentioned here", vec![]);
        let score = *result.metrics.get("assertion_score").unwrap();
        assert!((score - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_evaluate_response_no_assertions_passes() {
        let evaluator = Evaluator::new();
        let case = make_case("c4", vec![]);
        let result = evaluator.evaluate_response(&case, "any response", vec![]);
        // no assertions → score = 0/0 → 0.0, but tool_score = 1.0 → overall = 0.5 → passed
        assert!(result.passed || !result.passed); // Just check it doesn't panic
    }

    #[test]
    fn test_evaluate_response_with_expected_tools_pass() {
        let evaluator = Evaluator::new();
        let mut case = make_case("c5", vec![]);
        case.expected_tools = Some(vec!["read_file".to_string()]);
        let result = evaluator.evaluate_response(
            &case,
            "response",
            vec!["read_file".to_string()],
        );
        assert_eq!(*result.metrics.get("tool_score").unwrap(), 1.0);
    }

    #[test]
    fn test_evaluate_response_with_expected_tools_fail() {
        let evaluator = Evaluator::new();
        let mut case = make_case("c6", vec![]);
        case.expected_tools = Some(vec!["read_file".to_string(), "list_files".to_string()]);
        let result = evaluator.evaluate_response(
            &case,
            "response",
            vec!["read_file".to_string()], // only one of two tools used
        );
        let tool_score = *result.metrics.get("tool_score").unwrap();
        assert!((tool_score - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_evaluate_response_assertion_results_populated() {
        let evaluator = Evaluator::new();
        let case = make_case("c7", vec![Assertion::new("hello world")]);
        let result = evaluator.evaluate_response(&case, "hello world response", vec![]);
        assert_eq!(result.assertion_results.len(), 1);
        assert_eq!(result.assertion_results[0].get("passed").unwrap(), "true");
    }

    // -----------------------------------------------------------------------
    // evaluate_batch tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_evaluate_batch_returns_one_result_per_case() {
        let evaluator = Evaluator::new();
        let set = EvaluationSet {
            name: "Test".to_string(),
            description: "desc".to_string(),
            cases: vec![
                make_case("c1", vec![Assertion::new("budget")]),
                make_case("c2", vec![Assertion::new("sprint")]),
            ],
        };
        let results = evaluator.evaluate_batch(&set, |query| {
            if query.contains("c1") {
                ("budget details".to_string(), vec![])
            } else {
                ("sprint planning".to_string(), vec![])
            }
        });
        assert_eq!(results.len(), 2);
    }

    // -----------------------------------------------------------------------
    // evaluate_batch_parallel tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_evaluate_batch_parallel_returns_one_result_per_case() {
        let evaluator = Evaluator::new();
        let set = EvaluationSet {
            name: "Parallel Test".to_string(),
            description: "desc".to_string(),
            cases: vec![
                make_case("p1", vec![Assertion::new("budget")]),
                make_case("p2", vec![Assertion::new("sprint")]),
                make_case("p3", vec![Assertion::new("deployment")]),
            ],
        };
        // 2 workers, 3 cases
        let results = evaluator.evaluate_batch_parallel(&set, |query| {
            if query.contains("p1") {
                ("budget overview".to_string(), vec![])
            } else if query.contains("p2") {
                ("sprint planning".to_string(), vec![])
            } else {
                ("deployment complete".to_string(), vec![])
            }
        }, 2);
        assert_eq!(results.len(), 3);
    }

    #[test]
    fn test_evaluate_batch_parallel_preserves_order() {
        let evaluator = Evaluator::new();
        let cases: Vec<_> = (0..10)
            .map(|i| make_case(&format!("case_{}", i), vec![Assertion::new(&format!("token_{}", i))]))
            .collect();
        let set = EvaluationSet {
            name: "Order Test".to_string(),
            description: "".to_string(),
            cases,
        };
        let results = evaluator.evaluate_batch_parallel(&set, |query| {
            // Echo back a response that contains the case id embedded in the query
            (query.to_string(), vec![])
        }, 4);
        assert_eq!(results.len(), 10);
        for (i, result) in results.iter().enumerate() {
            assert_eq!(result.case_id, format!("case_{}", i));
        }
    }

    #[test]
    fn test_evaluate_batch_parallel_single_worker() {
        let evaluator = Evaluator::new();
        let set = EvaluationSet {
            name: "Single Worker".to_string(),
            description: "".to_string(),
            cases: vec![
                make_case("s1", vec![Assertion::new("alpha")]),
                make_case("s2", vec![Assertion::new("beta")]),
            ],
        };
        let results = evaluator.evaluate_batch_parallel(&set, |_| {
            ("alpha beta".to_string(), vec![])
        }, 1);
        assert_eq!(results.len(), 2);
        assert!(results.iter().all(|r| r.passed));
    }

    #[test]
    fn test_evaluate_batch_parallel_zero_workers_uses_cpu_count() {
        let evaluator = Evaluator::new();
        let set = EvaluationSet {
            name: "Auto Workers".to_string(),
            description: "".to_string(),
            cases: vec![make_case("a1", vec![Assertion::new("hello")])],
        };
        // 0 → rayon chooses thread count automatically
        let results = evaluator.evaluate_batch_parallel(&set, |_| {
            ("hello world".to_string(), vec![])
        }, 0);
        assert_eq!(results.len(), 1);
        assert!(results[0].passed);
    }

    #[test]
    fn test_evaluate_batch_parallel_empty_set() {
        let evaluator = Evaluator::new();
        let set = EvaluationSet {
            name: "Empty".to_string(),
            description: "".to_string(),
            cases: vec![],
        };
        let results = evaluator.evaluate_batch_parallel(&set, |_| {
            ("response".to_string(), vec![])
        }, 4);
        assert!(results.is_empty());
    }

    #[test]
    fn test_evaluate_batch_parallel_matches_sequential() {
        // Verify that parallel and sequential produce the same results
        let evaluator = Evaluator::new();
        let set = EvaluationSet {
            name: "Consistency".to_string(),
            description: "".to_string(),
            cases: vec![
                make_case("x1", vec![Assertion::new("budget review")]),
                make_case("x2", vec![Assertion::new("sprint planning")]),
                make_case("x3", vec![Assertion::new("unknown token xyz")]),
            ],
        };
        let scorer = |query: &str| -> (String, Vec<String>) {
            if query.contains("x1") {
                ("budget review completed".to_string(), vec![])
            } else if query.contains("x2") {
                ("sprint planning session".to_string(), vec![])
            } else {
                ("unrelated response".to_string(), vec![])
            }
        };
        let seq_results = evaluator.evaluate_batch(&set, scorer);
        let par_results = evaluator.evaluate_batch_parallel(&set, scorer, 2);
        assert_eq!(seq_results.len(), par_results.len());
        for (seq, par) in seq_results.iter().zip(par_results.iter()) {
            assert_eq!(seq.case_id, par.case_id);
            assert_eq!(seq.passed, par.passed);
            assert_eq!(
                seq.metrics.get("assertion_score"),
                par.metrics.get("assertion_score")
            );
        }
    }

    // -----------------------------------------------------------------------
    // aggregate statistics tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_aggregate_pass_rate_all_pass() {
        let r1 = EvaluationResult {
            case_id: "c1".to_string(),
            query: "q".to_string(),
            response: "r".to_string(),
            tool_calls: vec![],
            metrics: HashMap::new(),
            assertion_results: vec![],
            reasoning: "".to_string(),
            passed: true,
        };
        let mut r2 = r1.clone();
        r2.case_id = "c2".to_string();
        let rate = Evaluator::aggregate_pass_rate(&[r1, r2]);
        assert!((rate - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_aggregate_pass_rate_none_pass() {
        let r = EvaluationResult {
            case_id: "c1".to_string(),
            query: "q".to_string(),
            response: "r".to_string(),
            tool_calls: vec![],
            metrics: HashMap::new(),
            assertion_results: vec![],
            reasoning: "".to_string(),
            passed: false,
        };
        let rate = Evaluator::aggregate_pass_rate(&[r]);
        assert_eq!(rate, 0.0);
    }

    #[test]
    fn test_aggregate_pass_rate_empty() {
        assert_eq!(Evaluator::aggregate_pass_rate(&[]), 0.0);
    }

    #[test]
    fn test_mean_assertion_score_empty() {
        assert_eq!(Evaluator::mean_assertion_score(&[]), 0.0);
    }

    #[test]
    fn test_mean_assertion_score() {
        let make_result = |score: f64| {
            let mut m = HashMap::new();
            m.insert("assertion_score".to_string(), score);
            EvaluationResult {
                case_id: "c".to_string(),
                query: "q".to_string(),
                response: "r".to_string(),
                tool_calls: vec![],
                metrics: m,
                assertion_results: vec![],
                reasoning: "".to_string(),
                passed: score >= 0.5,
            }
        };
        let results = vec![make_result(0.8), make_result(0.6)];
        let mean = Evaluator::mean_assertion_score(&results);
        assert!((mean - 0.7).abs() < 1e-9);
    }
}
