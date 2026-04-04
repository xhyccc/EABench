//! LLM providers that delegate to the official OpenAI Python SDK via a thin
//! subprocess bridge (`python/llm_bridge.py`).
//!
//! Each provider serialises the request to JSON, spawns the bridge as a child
//! process, writes the JSON to its stdin, reads the JSON response from stdout,
//! and deserialises it back into an [`LLMResponse`].
//!
//! The bridge handles authentication, TLS, retry/back-off, and timeout via
//! the official `openai` Python package — no raw HTTP code lives in Rust.
//!
//! # Locating the bridge and Python interpreter
//!
//! At compile time `CARGO_MANIFEST_DIR` refers to the `rust/` directory, so
//! `<CARGO_MANIFEST_DIR>/../python/llm_bridge.py` is the bridge script and
//! `<CARGO_MANIFEST_DIR>/../.venv/bin/python` is the preferred interpreter.
//!
//! Both paths can be overridden at runtime:
//! * `EABENCH_BRIDGE_SCRIPT` – absolute path to `llm_bridge.py`
//! * `EABENCH_PYTHON`        – Python interpreter to use

use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use super::llm_provider::{LLMProvider, LLMResponse, Message, ToolCall};

// ---------------------------------------------------------------------------
// Locate runtime resources
// ---------------------------------------------------------------------------

/// Return the path to `llm_bridge.py`.
fn bridge_script() -> PathBuf {
    if let Ok(p) = std::env::var("EABENCH_BRIDGE_SCRIPT") {
        return PathBuf::from(p);
    }
    // CARGO_MANIFEST_DIR == …/rust, so parent() == repo root
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or(Path::new("."))
        .join("python")
        .join("llm_bridge.py")
}

/// Return the Python interpreter to use.
fn python_interpreter() -> String {
    if let Ok(p) = std::env::var("EABENCH_PYTHON") {
        return p;
    }
    let venv_python = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or(Path::new("."))
        .join(".venv")
        .join("bin")
        .join("python");
    if venv_python.exists() {
        return venv_python.to_string_lossy().to_string();
    }
    "python3".to_string()
}

// ---------------------------------------------------------------------------
// Shared message builder
// ---------------------------------------------------------------------------

/// Serialise `history` into the JSON array format expected by the OpenAI API.
fn build_messages(history: &[Message]) -> Vec<Value> {
    history
        .iter()
        .map(|msg| {
            let mut obj = json!({ "role": msg.role });
            if let Some(content) = &msg.content {
                obj["content"] = json!(content);
            } else if msg.role == "assistant" && msg.tool_calls.is_some() {
                obj["content"] = Value::Null;
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
        .collect()
}

// ---------------------------------------------------------------------------
// Bridge invocation
// ---------------------------------------------------------------------------

/// Invoke `llm_bridge.py` with `request`, return the parsed [`LLMResponse`].
fn call_bridge(request: &Value) -> Result<LLMResponse> {
    let python = python_interpreter();
    let script = bridge_script();

    let mut child = Command::new(&python)
        .arg(&script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| {
            format!(
                "Failed to spawn Python bridge `{} {}`. \
                 Ensure Python is installed and `openai` is available \
                 (pip install openai). \
                 Override with EABENCH_PYTHON / EABENCH_BRIDGE_SCRIPT.",
                python,
                script.display()
            )
        })?;

    // Write request to stdin then close it so the bridge sees EOF.
    {
        let stdin = child.stdin.take().expect("stdin is piped");
        let mut w = std::io::BufWriter::new(stdin);
        w.write_all(request.to_string().as_bytes())
            .context("writing to llm_bridge stdin")?;
    }

    let output = child.wait_with_output().context("waiting for llm_bridge")?;
    let stdout = String::from_utf8_lossy(&output.stdout);

    // The bridge always writes a JSON object. Check for {"error":"..."} first.
    if let Ok(v) = serde_json::from_str::<Value>(&stdout) {
        if let Some(err_msg) = v.get("error").and_then(|e| e.as_str()) {
            bail!("LLM bridge error: {}", err_msg);
        }
        if output.status.success() {
            return parse_bridge_response(v);
        }
    }

    // Non-zero exit without a parseable error object.
    let stderr = String::from_utf8_lossy(&output.stderr);
    bail!(
        "LLM bridge exited with {}\nstdout: {}\nstderr: {}",
        output.status,
        stdout,
        stderr
    );
}

/// Parse the bridge's success-response JSON into an [`LLMResponse`].
///
/// Bridge output:
/// ```json
/// {
///   "content":    "…" | null,
///   "tool_calls": [{"id":"…","name":"…","arguments":{…}}, …] | null,
///   "usage":      {"prompt_tokens":N,"completion_tokens":N,"total_tokens":N} | null
/// }
/// ```
fn parse_bridge_response(response: Value) -> Result<LLMResponse> {
    let content = response
        .get("content")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let tool_calls = response
        .get("tool_calls")
        .and_then(|v| v.as_array())
        .and_then(|arr| {
            if arr.is_empty() {
                return None;
            }
            let tcs: Vec<ToolCall> = arr
                .iter()
                .filter_map(|tc| {
                    let id = tc.get("id")?.as_str()?.to_string();
                    let name = tc.get("name")?.as_str()?.to_string();
                    let arguments: HashMap<String, Value> = tc
                        .get("arguments")
                        .and_then(|v| v.as_object())
                        .map(|obj| obj.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
                        .unwrap_or_default();
                    Some(ToolCall { id, name, arguments })
                })
                .collect();
            if tcs.is_empty() { None } else { Some(tcs) }
        });

    let usage = response
        .get("usage")
        .and_then(|u| u.as_object())
        .map(|obj| {
            obj.iter()
                .filter_map(|(k, v)| v.as_u64().map(|n| (k.clone(), n as u32)))
                .collect::<HashMap<String, u32>>()
        });

    Ok(LLMResponse { content, tool_calls, usage })
}

// ---------------------------------------------------------------------------
// OpenAIProvider
// ---------------------------------------------------------------------------

/// LLM provider that calls the OpenAI Chat Completions API (or any
/// OpenAI-compatible endpoint) via the official `openai` Python SDK.
pub struct OpenAIProvider {
    api_key: String,
    base_url: Option<String>,
    model: String,
    temperature: f64,
}

impl OpenAIProvider {
    /// Create a new `OpenAIProvider`.
    ///
    /// * `base_url` – custom endpoint (e.g. SiliconFlow).  Pass `None` or an
    ///   empty string to use the default OpenAI endpoint.
    pub fn new(
        api_key: impl Into<String>,
        base_url: Option<impl Into<String>>,
        model: impl Into<String>,
        temperature: f64,
    ) -> Self {
        let base = base_url
            .map(|s| s.into())
            .filter(|s: &String| !s.is_empty());
        OpenAIProvider {
            api_key: api_key.into(),
            base_url: base,
            model: model.into(),
            temperature,
        }
    }
}

impl LLMProvider for OpenAIProvider {
    fn generate(&self, history: &[Message], tools: &[Value]) -> Result<LLMResponse> {
        let mut config = json!({
            "api_key":     self.api_key,
            "model":       self.model,
            "temperature": self.temperature,
        });
        if let Some(ref url) = self.base_url {
            config["base_url"] = json!(url);
        }
        let request = json!({
            "provider": "openai",
            "config":   config,
            "messages": build_messages(history),
            "tools":    tools,
        });
        call_bridge(&request)
    }
}

// ---------------------------------------------------------------------------
// AzureOpenAIProvider
// ---------------------------------------------------------------------------

/// LLM provider that calls the Azure OpenAI Chat Completions API via the
/// official `openai` Python SDK.
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
        let request = json!({
            "provider": "azure",
            "config": {
                "api_key":         self.api_key,
                "azure_endpoint":  self.azure_endpoint,
                "deployment_name": self.deployment_name,
                "api_version":     self.api_version,
                "temperature":     self.temperature,
            },
            "messages": build_messages(history),
            "tools":    tools,
        });
        call_bridge(&request)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_openai_provider_default_base_url_is_none() {
        let p = OpenAIProvider::new("sk-test", None::<String>, "gpt-4o", 0.7);
        assert!(p.base_url.is_none());
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
        assert_eq!(p.base_url.as_deref(), Some("https://my-proxy.example.com/v1"));
    }

    #[test]
    fn test_openai_provider_empty_base_url_becomes_none() {
        let p = OpenAIProvider::new("sk-test", Some(""), "gpt-4", 0.7);
        assert!(p.base_url.is_none());
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
    fn test_parse_bridge_response_content() {
        let resp = json!({
            "content": "Hello, world!",
            "tool_calls": null,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15
            }
        });
        let result = parse_bridge_response(resp).unwrap();
        assert_eq!(result.content.as_deref(), Some("Hello, world!"));
        assert!(result.tool_calls.is_none());
        let usage = result.usage.unwrap();
        assert_eq!(*usage.get("total_tokens").unwrap(), 15u32);
    }

    #[test]
    fn test_parse_bridge_response_tool_calls() {
        let resp = json!({
            "content": null,
            "tool_calls": [{
                "id":        "call_abc123",
                "name":      "read_file",
                "arguments": {"path": "data/doc.txt"}
            }],
            "usage": null
        });
        let result = parse_bridge_response(resp).unwrap();
        let tcs = result.tool_calls.unwrap();
        assert_eq!(tcs.len(), 1);
        assert_eq!(tcs[0].name, "read_file");
        assert_eq!(
            tcs[0].arguments.get("path").and_then(|v| v.as_str()),
            Some("data/doc.txt")
        );
    }

    #[test]
    fn test_parse_bridge_response_empty_tool_calls_becomes_none() {
        let resp = json!({
            "content": "response",
            "tool_calls": [],
            "usage": null
        });
        let result = parse_bridge_response(resp).unwrap();
        assert!(result.tool_calls.is_none());
    }
}
