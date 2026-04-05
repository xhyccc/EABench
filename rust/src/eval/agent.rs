//! Minimal ReAct agent for evaluation.
//!
//! Mirrors the Python `AgentRunner` flow:
//!   1. Build [system, user] history
//!   2. Call LLM (with tool definitions)
//!   3. If LLM returns tool_calls → execute each with the keyword SearchEngine,
//!      append tool-result messages, repeat
//!   4. If LLM returns a text response → return it
//!
//! The agent stops after `max_turns` iterations even if no final text
//! response was produced (returns the last assistant content).

use anyhow::Result;
use serde_json::{json, Value};

use crate::generator::llm_provider::{LLMProvider, Message};
use crate::search::SearchEngine;

const TOP_K: usize = 5;
const SNIPPET_LEN: usize = 600;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// Output of a single agent run.
pub struct AgentResult {
    /// Final text response produced by the agent.
    pub response: String,
    /// Tool calls made during the run: `(tool_name, short_result_snippet)`.
    pub tool_calls_log: Vec<(String, String)>,
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Run a ReAct agent on `query` and return the final response.
///
/// * `llm`           – LLM provider (OpenAI / Azure)
/// * `search_engine` – per-case instance (will call `set_user_context`)
/// * `system_prompt` – the agent's system prompt (from agent config YAML)
/// * `user_id`       – optional; sets the search-engine access-control context
/// * `query`         – the user's natural-language question
/// * `max_turns`     – maximum tool-call rounds before forcing a final answer
pub fn run_react_agent(
    llm: &dyn LLMProvider,
    search_engine: &mut SearchEngine,
    system_prompt: &str,
    user_id: Option<&str>,
    query: &str,
    max_turns: usize,
) -> Result<AgentResult> {
    if let Some(uid) = user_id {
        search_engine.set_user_context(uid);
    }

    let tools = build_tool_definitions();

    let mut history: Vec<Message> = vec![
        Message {
            role: "system".to_string(),
            content: Some(system_prompt.to_string()),
            tool_calls: None,
            tool_call_id: None,
        },
        Message {
            role: "user".to_string(),
            content: Some(query.to_string()),
            tool_calls: None,
            tool_call_id: None,
        },
    ];

    let mut tool_calls_log: Vec<(String, String)> = Vec::new();

    for _ in 0..max_turns {
        let resp = llm.generate(&history, &tools)?;

        match resp.tool_calls.as_ref() {
            Some(tcs) if !tcs.is_empty() => {
                // Append the assistant message that contains the tool_calls
                history.push(Message {
                    role: "assistant".to_string(),
                    content: resp.content.clone(),
                    tool_calls: Some(tcs.clone()),
                    tool_call_id: None,
                });

                // Execute each tool and append its result
                for tc in tcs {
                    let query_arg = tc
                        .arguments
                        .get("query")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");

                    let result = execute_tool(&tc.name, query_arg, search_engine);
                    let snippet: String = result.chars().take(200).collect();
                    tool_calls_log.push((tc.name.clone(), snippet));

                    history.push(Message {
                        role: "tool".to_string(),
                        content: Some(result),
                        tool_calls: None,
                        tool_call_id: Some(tc.id.clone()),
                    });
                }
            }
            _ => {
                // No tool calls → this is the final text response
                let content = resp.content.unwrap_or_default();
                return Ok(AgentResult { response: content, tool_calls_log });
            }
        }
    }

    // Max turns reached: return the last assistant text content we recorded,
    // or a fallback message.
    let last = history
        .iter()
        .rev()
        .find(|m| m.role == "assistant" && m.tool_calls.is_none())
        .and_then(|m| m.content.clone())
        .unwrap_or_else(|| "Agent reached max turns without producing a final answer.".to_string());

    Ok(AgentResult { response: last, tool_calls_log })
}

// ---------------------------------------------------------------------------
// Tool execution
// ---------------------------------------------------------------------------

fn execute_tool(name: &str, query: &str, se: &SearchEngine) -> String {
    let results = match name {
        "search_email"   => se.search_emails(query, TOP_K),
        "search_file"    => se.search_files(query, TOP_K),
        "search_chat"    => se.search_chats(query, TOP_K),
        "search_meeting" => se.search_meetings(query, TOP_K),
        "search_people"  => se.search_people(query, TOP_K),
        _                => se.search_all(query, TOP_K),
    };

    if results.is_empty() {
        return format!("No results found for query: {:?}", query);
    }

    results
        .iter()
        .enumerate()
        .map(|(i, r)| {
            let id = r.metadata.get("id").map(|s| s.as_str()).unwrap_or("");
            let snippet: String = r.snippet.chars().take(SNIPPET_LEN).collect();
            format!(
                "[{}] [{}] {}{}\n{}",
                i + 1,
                r.kind,
                r.title,
                if id.is_empty() { String::new() } else { format!(" (id: {})", id) },
                snippet
            )
        })
        .collect::<Vec<_>>()
        .join("\n\n---\n\n")
}

// ---------------------------------------------------------------------------
// Tool definitions (JSON schema passed to the LLM)
// ---------------------------------------------------------------------------

fn build_tool_definitions() -> Vec<Value> {
    vec![
        tool_def(
            "search_email",
            "Search emails by keyword, subject, sender, or topic. Returns matching email subjects and bodies.",
        ),
        tool_def(
            "search_file",
            "Search files and documents by name, path, or content snippet.",
        ),
        tool_def(
            "search_chat",
            "Search direct messages and group chat conversations.",
        ),
        tool_def(
            "search_meeting",
            "Search meetings by title, agenda, or transcript content.",
        ),
        tool_def(
            "search_people",
            "Find user profiles by name, username, department, title, or role.",
        ),
    ]
}

fn tool_def(name: &str, description: &str) -> Value {
    json!({
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string"
                    }
                },
                "required": ["query"]
            }
        }
    })
}
