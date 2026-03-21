use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ProviderType {
    Openai,
    Azure,
    Anthropic,
    Local,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum FlowStrategy {
    React,
    Chain,
    Researcher,
}

// ---------------------------------------------------------------------------
// Sub-configs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ModelConfig {
    pub provider: ProviderType,
    pub name: String,
    #[serde(default)]
    pub parameters: HashMap<String, serde_yaml::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct EmbeddingConfig {
    pub provider: ProviderType,
    pub model: String,
    #[serde(default)]
    pub parameters: HashMap<String, serde_yaml::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ToolConfig {
    pub definitions: Vec<String>,
    #[serde(default)]
    pub config: HashMap<String, serde_yaml::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct FlowConfig {
    pub strategy: FlowStrategy,
    #[serde(default = "default_max_turns")]
    pub max_turns: u32,
}

fn default_max_turns() -> u32 {
    10
}

// ---------------------------------------------------------------------------
// AgentConfig
// ---------------------------------------------------------------------------

/// Agent configuration loaded from a YAML file.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct AgentConfig {
    pub id: String,
    pub version: String,
    pub model: ModelConfig,
    pub embedding: Option<EmbeddingConfig>,
    pub system_prompt: String,
    pub planning_prompt: Option<String>,
    #[serde(default)]
    pub dynamic_keys: Vec<String>,
    pub tools: ToolConfig,
    pub flow: FlowConfig,
}

impl AgentConfig {
    /// Load an [`AgentConfig`] from a YAML file.
    pub fn from_yaml(path: &Path) -> Result<Self> {
        let raw = fs::read_to_string(path)
            .with_context(|| format!("reading {}", path.display()))?;
        let config: AgentConfig =
            serde_yaml::from_str(&raw).with_context(|| format!("parsing {}", path.display()))?;
        Ok(config)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn write_yaml(dir: &TempDir, name: &str, content: &str) -> std::path::PathBuf {
        let path = dir.path().join(name);
        let mut f = std::fs::File::create(&path).unwrap();
        write!(f, "{}", content).unwrap();
        path
    }

    fn make_agent_yaml(dir: &TempDir) -> std::path::PathBuf {
        let yaml = r#"
id: test-agent
version: "1.0"
model:
  provider: openai
  name: gpt-4o
system_prompt: "You are helpful. {user_profile}"
tools:
  definitions: [read_file, list_files]
flow:
  strategy: react
  max_turns: 5
"#;
        write_yaml(dir, "agent.yaml", yaml)
    }

    #[test]
    fn test_from_yaml_loads_id_and_model() {
        let dir = TempDir::new().unwrap();
        let path = make_agent_yaml(&dir);
        let cfg = AgentConfig::from_yaml(&path).unwrap();
        assert_eq!(cfg.id, "test-agent");
        assert_eq!(cfg.model.name, "gpt-4o");
        assert_eq!(cfg.model.provider, ProviderType::Openai);
    }

    #[test]
    fn test_from_yaml_loads_flow() {
        let dir = TempDir::new().unwrap();
        let path = make_agent_yaml(&dir);
        let cfg = AgentConfig::from_yaml(&path).unwrap();
        assert_eq!(cfg.flow.strategy, FlowStrategy::React);
        assert_eq!(cfg.flow.max_turns, 5);
    }

    #[test]
    fn test_from_yaml_loads_tools() {
        let dir = TempDir::new().unwrap();
        let path = make_agent_yaml(&dir);
        let cfg = AgentConfig::from_yaml(&path).unwrap();
        assert!(cfg.tools.definitions.contains(&"read_file".to_string()));
        assert!(cfg.tools.definitions.contains(&"list_files".to_string()));
    }

    #[test]
    fn test_default_max_turns() {
        let yaml = r#"
id: a
version: "1"
model:
  provider: azure
  name: gpt-4
system_prompt: test
tools:
  definitions: []
flow:
  strategy: chain
"#;
        let dir = TempDir::new().unwrap();
        let path = write_yaml(&dir, "agent.yaml", yaml);
        let cfg = AgentConfig::from_yaml(&path).unwrap();
        assert_eq!(cfg.flow.max_turns, 10);
    }

    #[test]
    fn test_optional_embedding_and_planning_prompt() {
        let dir = TempDir::new().unwrap();
        let path = make_agent_yaml(&dir);
        let cfg = AgentConfig::from_yaml(&path).unwrap();
        assert!(cfg.embedding.is_none());
        assert!(cfg.planning_prompt.is_none());
    }

    #[test]
    fn test_all_flow_strategies() {
        for (strategy_str, expected) in [
            ("react", FlowStrategy::React),
            ("chain", FlowStrategy::Chain),
            ("researcher", FlowStrategy::Researcher),
        ] {
            let yaml = format!(
                r#"
id: a
version: "1"
model:
  provider: openai
  name: gpt-4o
system_prompt: test
tools:
  definitions: []
flow:
  strategy: {}
"#,
                strategy_str
            );
            let dir = TempDir::new().unwrap();
            let path = {
                let p = dir.path().join("agent.yaml");
                let mut f = std::fs::File::create(&p).unwrap();
                write!(f, "{}", yaml).unwrap();
                p
            };
            let cfg = AgentConfig::from_yaml(&path).unwrap();
            assert_eq!(cfg.flow.strategy, expected);
        }
    }
}
