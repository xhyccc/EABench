use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// StoryConfig – input to the data generation pipeline
// ---------------------------------------------------------------------------

/// Configuration describing the company and scenario to simulate.
///
/// Mirrors `src.generator.models.StoryConfig` in the Python implementation.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct StoryConfig {
    /// Company name (used in prompt context and tenant ID).
    pub company_name: String,
    /// Industry vertical (e.g. "Software", "Finance").
    pub industry: String,
    /// Company size: "small", "medium", or "large".
    #[serde(default = "default_company_size")]
    pub company_size: String,
    /// Number of synthetic users to generate.
    #[serde(default = "default_num_users")]
    pub num_users: usize,
    /// Number of days to simulate.
    #[serde(default = "default_duration_days")]
    pub duration_days: usize,
    /// Batch size used when generating users and eval cases.
    #[serde(default = "default_eval_batch_size")]
    pub eval_batch_size: usize,
    /// High-level milestones / key events that drive the narrative.
    #[serde(default)]
    pub key_events: Vec<String>,
    /// Detailed free-text description of the company / scenario.
    pub description: String,
}

fn default_company_size() -> String {
    "small".to_string()
}
fn default_num_users() -> usize {
    5
}
fn default_duration_days() -> usize {
    7
}
fn default_eval_batch_size() -> usize {
    5
}

impl StoryConfig {
    /// Convenience constructor with mandatory fields only.
    pub fn new(
        company_name: impl Into<String>,
        industry: impl Into<String>,
        description: impl Into<String>,
    ) -> Self {
        StoryConfig {
            company_name: company_name.into(),
            industry: industry.into(),
            company_size: default_company_size(),
            num_users: default_num_users(),
            duration_days: default_duration_days(),
            eval_batch_size: default_eval_batch_size(),
            key_events: vec![],
            description: description.into(),
        }
    }
}

// ---------------------------------------------------------------------------
// GenerationOutput – result of the data generation pipeline
// ---------------------------------------------------------------------------

/// Output produced by [`crate::generator::pipeline::DataGenerator::generate_tenant`].
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct GenerationOutput {
    /// Unique identifier for the generated tenant.
    pub tenant_id: String,
    /// Absolute path to the directory containing the generated data.
    pub base_path: String,
    /// Human-readable summary of the generation run.
    pub summary: String,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_story_config_new_sets_required_fields() {
        let cfg = StoryConfig::new("Acme Corp", "Software", "A software company");
        assert_eq!(cfg.company_name, "Acme Corp");
        assert_eq!(cfg.industry, "Software");
        assert_eq!(cfg.description, "A software company");
    }

    #[test]
    fn test_story_config_defaults() {
        let cfg = StoryConfig::new("Acme", "Tech", "A tech company");
        assert_eq!(cfg.company_size, "small");
        assert_eq!(cfg.num_users, 5);
        assert_eq!(cfg.duration_days, 7);
        assert_eq!(cfg.eval_batch_size, 5);
        assert!(cfg.key_events.is_empty());
    }

    #[test]
    fn test_story_config_custom_fields() {
        let cfg = StoryConfig {
            company_name: "BigCorp".to_string(),
            industry: "Finance".to_string(),
            company_size: "large".to_string(),
            num_users: 50,
            duration_days: 30,
            eval_batch_size: 10,
            key_events: vec!["Launch v2".to_string(), "Merger announcement".to_string()],
            description: "A large financial firm".to_string(),
        };
        assert_eq!(cfg.num_users, 50);
        assert_eq!(cfg.duration_days, 30);
        assert_eq!(cfg.key_events.len(), 2);
        assert_eq!(cfg.company_size, "large");
    }

    #[test]
    fn test_story_config_key_events_populated() {
        let cfg = StoryConfig {
            key_events: vec!["Project Alpha Kickoff".to_string()],
            ..StoryConfig::new("X", "Y", "Z")
        };
        assert_eq!(cfg.key_events[0], "Project Alpha Kickoff");
    }

    #[test]
    fn test_generation_output_fields() {
        let out = GenerationOutput {
            tenant_id: "acme-20250101".to_string(),
            base_path: "/tmp/tenants/acme-20250101".to_string(),
            summary: "Generated 5 users".to_string(),
        };
        assert_eq!(out.tenant_id, "acme-20250101");
        assert_eq!(out.base_path, "/tmp/tenants/acme-20250101");
        assert_eq!(out.summary, "Generated 5 users");
    }

    #[test]
    fn test_story_config_serde_roundtrip() {
        let original = StoryConfig {
            company_name: "TestCo".to_string(),
            industry: "Retail".to_string(),
            company_size: "medium".to_string(),
            num_users: 10,
            duration_days: 14,
            eval_batch_size: 5,
            key_events: vec!["Q1 Review".to_string()],
            description: "A mid-size retailer".to_string(),
        };
        let json_str = serde_json::to_string(&original).unwrap();
        let deserialized: StoryConfig = serde_json::from_str(&json_str).unwrap();
        assert_eq!(original, deserialized);
    }

    #[test]
    fn test_generation_output_serde_roundtrip() {
        let original = GenerationOutput {
            tenant_id: "testco-20250101".to_string(),
            base_path: "/tmp/testco".to_string(),
            summary: "All good".to_string(),
        };
        let json_str = serde_json::to_string(&original).unwrap();
        let deserialized: GenerationOutput = serde_json::from_str(&json_str).unwrap();
        assert_eq!(original, deserialized);
    }
}
