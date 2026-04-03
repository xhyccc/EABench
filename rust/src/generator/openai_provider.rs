use anyhow::{Context, Result};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;

use super::llm_provider::{LLMProvider, LLMResponse, Message, ToolCall};

// ---------------------------------------------------------------------------
// TLS helper – always use the OS-native TLS stack to avoid rustls
// compatibility issues with certain Azure endpoints.
// ---------------------------------------------------------------------------

fn make_agent() -> ureq::Agent {
    let connector = native_tls::TlsConnector::new()
        .expect("failed to create native TLS connector");
    ureq::AgentBuilder::new()
        .tls_connector(Arc::new(connector))
        .build()
}

// ---------------------------------------------------------------------------
// OpenAIProvider
// ---------------------------------------------------------------------------

/// LLM provider that calls the OpenAI Chat Completions API (or any
/// OpenAI-compatible endpoint such as Azure, local vLLM, etc.) using a
/// blocking HTTP request.
///
/// Mirrors `OpenAIProvider` in `src/core/openai_provider.py`.
pub struct OpenAIProvider {
    api_key: String,
    base_url: String,
    model: String,
    temperature: f64,
}

impl OpenAIProvider {
    /// Create a new `OpenAIProvider`.
    ///
    /// # Arguments
    /// * `api_key`   – OpenAI API key.
    /// * `base_url`  – Base URL for the API (e.g. `https://api.openai.com/v1`).
    ///                 Pass an empty string or `None` to use the default.
    /// * `model`     – Model name (e.g. `"gpt-4o"`).
    /// * `temperature` – Sampling temperature (default `0.7`).
    pub fn new(
        api_key: impl Into<String>,
        base_url: Option<impl Into<String>>,
        model: impl Into<String>,
        temperature: f64,
    ) -> Self {
        let default_base = "https://api.openai.com/v1".to_string();
        let base_url = base_url
            .map(|s| s.into())
            .filter(|s: &String| !s.is_empty())
            .unwrap_or(default_base);
        OpenAIProvider {
            api_key: api_key.into(),
            base_url,
            model: model.into(),
            temperature,
        }
    }
}

impl LLMProvider for OpenAIProvider {
    fn generate(&self, history: &[Message], tools: &[Value]) -> Result<LLMResponse> {
        let messages: Vec<Value> = history
            .iter()
            .map(|msg| {
                let mut obj = json!({ "role": msg.role });
                if let Some(content) = &msg.content {
                    obj["content"] = json!(content);
                } else if msg.role == "assistant" && msg.tool_calls.is_some() {
                    obj["content"] = json!("");
                }
                if let Some(tcs) = &msg.tool_calls {
                    let calls: Vec<Value> = tcs
                        .iter()
                        .map(|tc| {
                            json!({
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": serde_json::to_string(&tc.arguments)
                                        .unwrap_or_default()
                                }
                            })
                        })
                        .collect();
                    obj["tool_calls"] = json!(calls);
                }
                if let Some(id) = &msg.tool_call_id {
                    obj["tool_call_id"] = json!(id);
                }
                obj
            })
            .collect();

        let mut body = json!({
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature
        });

        if !tools.is_empty() {
            body["tools"] = json!(tools);
        }

        let url = format!("{}/chat/completions", self.base_url);
        let response: Value = make_agent().post(&url)
            .set("Authorization", &format!("Bearer {}", self.api_key))
            .set("Content-Type", "application/json")
            .send_json(&body)
            .with_context(|| format!("HTTP request to {}", url))?
            .into_json()
            .context("parsing OpenAI response JSON")?;

        parse_openai_response(response)
    }
}

// ---------------------------------------------------------------------------
// AzureOpenAIProvider
// ---------------------------------------------------------------------------

/// LLM provider that calls the Azure OpenAI Chat Completions API.
///
/// Mirrors `AzureOpenAIProvider` in `src/core/azure_provider.py`.
pub struct AzureOpenAIProvider {
    api_key: String,
    azure_endpoint: String,
    deployment_name: String,
    api_version: String,
    temperature: f64,
}

impl AzureOpenAIProvider {
    /// Create a new `AzureOpenAIProvider`.
    pub fn new(
        api_key: impl Into<String>,
        azure_endpoint: impl Into<String>,
        deployment_name: impl Into<String>,
        api_version: impl Into<String>,
        temperature: f64,
    ) -> Self {
        AzureOpenAIProvider {
            api_key: api_key.into(),
            azure_endpoint: azure_endpoint
                .into()
                .trim_end_matches('/')
                .to_string(),
            deployment_name: deployment_name.into(),
            api_version: api_version.into(),
            temperature,
        }
    }
}

impl LLMProvider for AzureOpenAIProvider {
    fn generate(&self, history: &[Message], tools: &[Value]) -> Result<LLMResponse> {
        let messages: Vec<Value> = history
            .iter()
            .map(|msg| {
                let mut obj = json!({ "role": msg.role });
                if let Some(content) = &msg.content {
                    obj["content"] = json!(content);
                } else if msg.role == "assistant" && msg.tool_calls.is_some() {
                    obj["content"] = json!("");
                }
                if let Some(tcs) = &msg.tool_calls {
                    let calls: Vec<Value> = tcs
                        .iter()
                        .map(|tc| {
                            json!({
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": serde_json::to_string(&tc.arguments)
                                        .unwrap_or_default()
                                }
                            })
                        })
                        .collect();
                    obj["tool_calls"] = json!(calls);
                }
                if let Some(id) = &msg.tool_call_id {
                    obj["tool_call_id"] = json!(id);
                }
                obj
            })
            .collect();

        let mut body = json!({
            "model": self.deployment_name,
            "messages": messages,
            "temperature": self.temperature
        });

        if !tools.is_empty() {
            body["tools"] = json!(tools);
        }

        let url = format!(
            "{}/openai/deployments/{}/chat/completions?api-version={}",
            self.azure_endpoint, self.deployment_name, self.api_version
        );

        let response: Value = make_agent().post(&url)
            .set("api-key", &self.api_key)
            .set("Content-Type", "application/json")
            .send_json(&body)
            .with_context(|| format!("HTTP request to {}", url))?
            .into_json()
            .context("parsing Azure OpenAI response JSON")?;

        parse_openai_response(response)
    }
}

// ---------------------------------------------------------------------------
// Shared response parser
// ---------------------------------------------------------------------------

fn parse_openai_response(response: Value) -> Result<LLMResponse> {
    let choice = response
        .get("choices")
        .and_then(|c| c.as_array())
        .and_then(|arr| arr.first())
        .with_context(|| "no choices in LLM response")?;

    let message = choice
        .get("message")
        .with_context(|| "no message in choice")?;

    let content = message.get("content").and_then(|v| v.as_str()).map(|s| s.to_string());

    let tool_calls = message.get("tool_calls").and_then(|v| v.as_array()).map(|arr| {
        arr.iter()
            .filter_map(|tc| {
                let id = tc.get("id")?.as_str()?.to_string();
                let func = tc.get("function")?;
                let name = func.get("name")?.as_str()?.to_string();
                let args_str = func.get("arguments")?.as_str().unwrap_or("{}");
                let arguments: HashMap<String, Value> =
                    serde_json::from_str(args_str).unwrap_or_default();
                Some(ToolCall { id, name, arguments })
            })
            .collect::<Vec<_>>()
    });

    let usage = response.get("usage").and_then(|u| u.as_object()).map(|obj| {
        obj.iter()
            .filter_map(|(k, v)| v.as_u64().map(|n| (k.clone(), n as u32)))
            .collect::<HashMap<String, u32>>()
    });

    Ok(LLMResponse {
        content,
        tool_calls: if tool_calls.as_ref().map(|v: &Vec<_>| v.is_empty()).unwrap_or(true) {
            None
        } else {
            tool_calls
        },
        usage,
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_openai_provider_new_default_base_url() {
        let p = OpenAIProvider::new("sk-test", None::<String>, "gpt-4o", 0.7);
        assert_eq!(p.base_url, "https://api.openai.com/v1");
        assert_eq!(p.model, "gpt-4o");
        assert!((p.temperature - 0.7).abs() < 1e-9);
    }

    #[test]
    fn test_openai_provider_custom_base_url() {
        let p = OpenAIProvider::new(
            "sk-test",
            Some("https://my-proxy.example.com/v1"),
            "gpt-4",
            0.5,
        );
        assert_eq!(p.base_url, "https://my-proxy.example.com/v1");
    }

    #[test]
    fn test_openai_provider_empty_base_url_uses_default() {
        let p = OpenAIProvider::new("sk-test", Some(""), "gpt-4", 0.7);
        assert_eq!(p.base_url, "https://api.openai.com/v1");
    }

    #[test]
    fn test_azure_provider_new() {
        let p = AzureOpenAIProvider::new(
            "key",
            "https://my.openai.azure.com/",
            "gpt-4-deployment",
            "2024-02-01",
            0.7,
        );
        assert_eq!(p.azure_endpoint, "https://my.openai.azure.com");
        assert_eq!(p.deployment_name, "gpt-4-deployment");
        assert_eq!(p.api_version, "2024-02-01");
    }

    #[test]
    fn test_azure_provider_strips_trailing_slash() {
        let p = AzureOpenAIProvider::new(
            "key",
            "https://endpoint.azure.com/",
            "deploy",
            "2023-05-15",
            0.7,
        );
        assert!(!p.azure_endpoint.ends_with('/'));
    }

    #[test]
    fn test_parse_openai_response_content() {
        let resp = json!({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Hello, world!"
                }
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15
            }
        });
        let result = parse_openai_response(resp).unwrap();
        assert_eq!(result.content.as_deref(), Some("Hello, world!"));
        assert!(result.tool_calls.is_none());
        let usage = result.usage.unwrap();
        assert_eq!(*usage.get("total_tokens").unwrap(), 15u32);
    }

    #[test]
    fn test_parse_openai_response_tool_calls() {
        let resp = json!({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": null,
                    "tool_calls": [{
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": "{\"path\": \"data/doc.txt\"}"
                        }
                    }]
                }
            }]
        });
        let result = parse_openai_response(resp).unwrap();
        let tcs = result.tool_calls.unwrap();
        assert_eq!(tcs.len(), 1);
        assert_eq!(tcs[0].name, "read_file");
        assert_eq!(
            tcs[0].arguments.get("path").and_then(|v| v.as_str()),
            Some("data/doc.txt")
        );
    }

    #[test]
    fn test_parse_openai_response_missing_choices_returns_error() {
        let resp = json!({"error": {"message": "API error"}});
        assert!(parse_openai_response(resp).is_err());
    }

    #[test]
    fn test_parse_openai_response_empty_tool_calls_becomes_none() {
        let resp = json!({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "response",
                    "tool_calls": []
                }
            }]
        });
        let result = parse_openai_response(resp).unwrap();
        assert!(result.tool_calls.is_none());
    }
}
