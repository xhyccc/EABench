use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// ToolCall
// ---------------------------------------------------------------------------

/// A tool call requested by the LLM.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub arguments: HashMap<String, Value>,
}

// ---------------------------------------------------------------------------
// Message
// ---------------------------------------------------------------------------

/// A single message in a conversation history.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Message {
    pub role: String,
    pub content: Option<String>,
    #[serde(default)]
    pub tool_calls: Option<Vec<ToolCall>>,
    pub tool_call_id: Option<String>,
}

impl Message {
    /// Create a user message.
    pub fn user(content: impl Into<String>) -> Self {
        Message {
            role: "user".to_string(),
            content: Some(content.into()),
            tool_calls: None,
            tool_call_id: None,
        }
    }

    /// Create an assistant message.
    pub fn assistant(content: impl Into<String>) -> Self {
        Message {
            role: "assistant".to_string(),
            content: Some(content.into()),
            tool_calls: None,
            tool_call_id: None,
        }
    }

    /// Create a tool result message.
    pub fn tool_result(tool_call_id: impl Into<String>, content: impl Into<String>) -> Self {
        Message {
            role: "tool".to_string(),
            content: Some(content.into()),
            tool_calls: None,
            tool_call_id: Some(tool_call_id.into()),
        }
    }
}

// ---------------------------------------------------------------------------
// LLMResponse
// ---------------------------------------------------------------------------

/// A response from the LLM provider.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct LLMResponse {
    pub content: Option<String>,
    pub tool_calls: Option<Vec<ToolCall>>,
    pub usage: Option<HashMap<String, u32>>,
}

// ---------------------------------------------------------------------------
// LLMProvider trait
// ---------------------------------------------------------------------------

/// Trait implemented by all LLM providers (OpenAI, Azure, Mock, …).
///
/// The interface is deliberately **synchronous** (blocking) to match the
/// rest of the Rust codebase's design philosophy (no Tokio runtime required).
pub trait LLMProvider: Send + Sync {
    /// Generate a response given a conversation history and optional tools.
    fn generate(&self, history: &[Message], tools: &[Value]) -> Result<LLMResponse>;

    /// Simple text completion for data-generation tasks.
    ///
    /// Default implementation wraps [`LLMProvider::generate`].
    fn get_completion(&self, messages: &[HashMap<String, String>]) -> Result<String> {
        let history: Vec<Message> = messages
            .iter()
            .map(|m| Message {
                role: m.get("role").cloned().unwrap_or_default(),
                content: m.get("content").cloned(),
                tool_calls: None,
                tool_call_id: None,
            })
            .collect();
        let response = self.generate(&history, &[])?;
        Ok(response.content.unwrap_or_default())
    }
}

// ---------------------------------------------------------------------------
// MockLLMProvider
// ---------------------------------------------------------------------------

/// A deterministic mock provider for use in unit tests.
///
/// Behaviour mirrors the Python `MockLLMProvider`:
/// - If the last message has `role = "tool"`, it returns a content response
///   summarising the tool result.
/// - If the last user message contains "list files", it calls the
///   `list_files` tool.
/// - Otherwise it returns the configured `response` string.
pub struct MockLLMProvider {
    /// The string returned as `content` for ordinary requests.
    pub response: String,
}

impl MockLLMProvider {
    pub fn new(response: impl Into<String>) -> Self {
        MockLLMProvider {
            response: response.into(),
        }
    }
}

impl Default for MockLLMProvider {
    fn default() -> Self {
        MockLLMProvider {
            response: "I am a mock agent.".to_string(),
        }
    }
}

impl LLMProvider for MockLLMProvider {
    fn generate(&self, history: &[Message], _tools: &[Value]) -> Result<LLMResponse> {
        let usage: HashMap<String, u32> = [
            ("prompt_tokens".to_string(), 5),
            ("completion_tokens".to_string(), 5),
            ("total_tokens".to_string(), 10),
        ]
        .into_iter()
        .collect();

        if let Some(msg) = history.last() {
            if msg.role == "tool" {
                let result_text = msg.content.as_deref().unwrap_or("");
                let usage_tool: HashMap<String, u32> = [
                    ("prompt_tokens".to_string(), 10),
                    ("completion_tokens".to_string(), 10),
                    ("total_tokens".to_string(), 20),
                ]
                .into_iter()
                .collect();
                return Ok(LLMResponse {
                    content: Some(format!(
                        "I have executed the tool. The result was: {}",
                        result_text
                    )),
                    tool_calls: None,
                    usage: Some(usage_tool),
                });
            }

            if msg.role == "user" {
                if let Some(content) = &msg.content {
                    if content.to_lowercase().contains("list files") {
                        let args: HashMap<String, Value> = [(
                            "path".to_string(),
                            Value::String(".".to_string()),
                        )]
                        .into_iter()
                        .collect();
                        return Ok(LLMResponse {
                            content: None,
                            tool_calls: Some(vec![ToolCall {
                                id: "call_1".to_string(),
                                name: "list_files".to_string(),
                                arguments: args,
                            }]),
                            usage: Some(usage),
                        });
                    }
                }
            }
        }

        Ok(LLMResponse {
            content: Some(self.response.clone()),
            tool_calls: None,
            usage: Some(usage),
        })
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // Data model tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_message_with_role_and_content() {
        let msg = Message::user("Hello");
        assert_eq!(msg.role, "user");
        assert_eq!(msg.content.as_deref(), Some("Hello"));
        assert!(msg.tool_calls.is_none());
    }

    #[test]
    fn test_message_assistant_constructor() {
        let msg = Message::assistant("Sure");
        assert_eq!(msg.role, "assistant");
        assert_eq!(msg.content.as_deref(), Some("Sure"));
    }

    #[test]
    fn test_message_tool_result_constructor() {
        let msg = Message::tool_result("tc1", "file1.txt\nfile2.txt");
        assert_eq!(msg.role, "tool");
        assert_eq!(msg.tool_call_id.as_deref(), Some("tc1"));
        assert_eq!(msg.content.as_deref(), Some("file1.txt\nfile2.txt"));
    }

    #[test]
    fn test_message_with_tool_calls() {
        let call = ToolCall {
            id: "tc1".to_string(),
            name: "read_file".to_string(),
            arguments: [("path".to_string(), Value::String("file.txt".to_string()))]
                .into_iter()
                .collect(),
        };
        let msg = Message {
            role: "assistant".to_string(),
            content: None,
            tool_calls: Some(vec![call]),
            tool_call_id: None,
        };
        assert_eq!(msg.tool_calls.as_ref().unwrap()[0].name, "read_file");
    }

    #[test]
    fn test_llm_response_content_only() {
        let resp = LLMResponse {
            content: Some("The answer is 42.".to_string()),
            tool_calls: None,
            usage: None,
        };
        assert_eq!(resp.content.as_deref(), Some("The answer is 42."));
        assert!(resp.tool_calls.is_none());
        assert!(resp.usage.is_none());
    }

    #[test]
    fn test_llm_response_with_tool_calls() {
        let call = ToolCall {
            id: "c1".to_string(),
            name: "list_files".to_string(),
            arguments: HashMap::new(),
        };
        let resp = LLMResponse {
            content: None,
            tool_calls: Some(vec![call]),
            usage: None,
        };
        assert_eq!(resp.tool_calls.as_ref().unwrap()[0].name, "list_files");
    }

    #[test]
    fn test_llm_response_with_usage() {
        let usage: HashMap<String, u32> = [
            ("prompt_tokens".to_string(), 10),
            ("completion_tokens".to_string(), 5),
            ("total_tokens".to_string(), 15),
        ]
        .into_iter()
        .collect();
        let resp = LLMResponse {
            content: Some("hi".to_string()),
            tool_calls: None,
            usage: Some(usage),
        };
        assert_eq!(*resp.usage.as_ref().unwrap().get("total_tokens").unwrap(), 15);
    }

    #[test]
    fn test_tool_call_fields() {
        let call = ToolCall {
            id: "x".to_string(),
            name: "execute_command".to_string(),
            arguments: [(
                "command".to_string(),
                Value::String("ls".to_string()),
            )]
            .into_iter()
            .collect(),
        };
        assert_eq!(call.id, "x");
        assert_eq!(call.arguments["command"], Value::String("ls".to_string()));
    }

    // -----------------------------------------------------------------------
    // MockLLMProvider tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_mock_provider_returns_response() {
        let provider = MockLLMProvider::default();
        let history = vec![Message::user("What is the weather?")];
        let resp = provider.generate(&history, &[]).unwrap();
        assert!(resp.content.is_some() || resp.tool_calls.is_some());
    }

    #[test]
    fn test_mock_provider_list_files_trigger() {
        let provider = MockLLMProvider::default();
        let history = vec![Message::user("Please list files in the directory")];
        let resp = provider.generate(&history, &[]).unwrap();
        assert!(resp.tool_calls.is_some());
        assert_eq!(resp.tool_calls.as_ref().unwrap()[0].name, "list_files");
    }

    #[test]
    fn test_mock_provider_tool_result_returns_content() {
        let provider = MockLLMProvider::default();
        let history = vec![
            Message::user("list files"),
            Message::tool_result("tc1", "file1.txt\nfile2.txt"),
        ];
        let resp = provider.generate(&history, &[]).unwrap();
        assert!(resp.content.is_some());
        let content = resp.content.unwrap();
        assert!(content.contains("result") || content.contains("file1.txt"));
    }

    #[test]
    fn test_mock_provider_get_completion_returns_string() {
        let provider = MockLLMProvider::new("Hello World");
        let messages = vec![{
            let mut m = HashMap::new();
            m.insert("role".to_string(), "user".to_string());
            m.insert("content".to_string(), "Hello".to_string());
            m
        }];
        let result = provider.get_completion(&messages).unwrap();
        assert_eq!(result, "Hello World");
    }

    #[test]
    fn test_mock_provider_custom_response() {
        let provider = MockLLMProvider::new("Custom response");
        let history = vec![Message::user("anything")];
        let resp = provider.generate(&history, &[]).unwrap();
        assert_eq!(resp.content.as_deref(), Some("Custom response"));
    }

    #[test]
    fn test_mock_provider_usage_populated() {
        let provider = MockLLMProvider::default();
        let history = vec![Message::user("test")];
        let resp = provider.generate(&history, &[]).unwrap();
        let usage = resp.usage.unwrap();
        assert!(usage.contains_key("total_tokens"));
    }

    #[test]
    fn test_mock_provider_case_insensitive_list_files() {
        let provider = MockLLMProvider::default();
        let history = vec![Message::user("LIST FILES please")];
        let resp = provider.generate(&history, &[]).unwrap();
        assert!(resp.tool_calls.is_some());
    }
}
