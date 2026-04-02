use anyhow::{Context, Result};
use chrono::{Duration, Local};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;

use crate::config::tenant_config::{
    Chat, ChatMessage, Email, FileMetadata, GroupChat, Meeting, TenantConfig, UserInfo, UserName,
    UserProfile,
};
use super::llm_provider::LLMProvider;
use super::models::{GenerationOutput, StoryConfig};

// ---------------------------------------------------------------------------
// Defaults for user profile fields not provided by the LLM
// ---------------------------------------------------------------------------

const DEFAULT_LOCATION: &str = "San Francisco";
const DEFAULT_TIMEZONE: &str = "America/Los_Angeles";

// ---------------------------------------------------------------------------
// Helper: template formatting
// ---------------------------------------------------------------------------

/// Replace `{key}` placeholders in `template` with the given values.
///
/// After substitution, `{{` is converted to `{` and `}}` to `}` so that
/// JSON examples embedded in prompt templates are preserved correctly (the
/// same behaviour as Python's `str.format()`).
pub fn format_template(template: &str, vars: &[(&str, &str)]) -> String {
    let mut result = template.to_string();
    for (key, value) in vars {
        result = result.replace(&format!("{{{}}}", key), value);
    }
    result.replace("{{", "{").replace("}}", "}")
}

// ---------------------------------------------------------------------------
// Helper: JSON extraction from LLM responses
// ---------------------------------------------------------------------------

/// Extract a JSON value from a (possibly markdown-wrapped) LLM response.
///
/// Mirrors `DataGenerator._parse_json` in the Python implementation:
/// 1. Strip a ` ```json … ``` ` code fence if present.
/// 2. Try to parse the whole string as JSON.
/// 3. Find the first `[` or `{` and use a greedy bracket scan to extract
///    the JSON object/array.
/// 4. Return an empty object `{}` on failure.
pub fn parse_json(text: &str) -> Value {
    // 1. Strip markdown code block
    let stripped = strip_markdown_code_block(text);
    let text = stripped.trim();

    // 2. Try direct parse
    if let Ok(v) = serde_json::from_str::<Value>(text) {
        return v;
    }

    // 3. Find first JSON start character
    let start_list = text.find('[');
    let start_dict = text.find('{');

    let start = match (start_list, start_dict) {
        (Some(l), Some(d)) => Some(if l < d { (l, ']') } else { (d, '}') }),
        (Some(l), None) => Some((l, ']')),
        (None, Some(d)) => Some((d, '}')),
        (None, None) => None,
    };

    if let Some((pos, close)) = start {
        let slice = &text[pos..];
        // Try raw decode (find the minimal valid JSON prefix)
        if let Ok(v) = serde_json::from_str::<Value>(slice) {
            return v;
        }
        // Greedy: find last matching close bracket
        if let Some(end) = text.rfind(close) {
            if end >= pos {
                if let Ok(v) = serde_json::from_str::<Value>(&text[pos..=end]) {
                    return v;
                }
            }
        }
    }

    Value::Object(serde_json::Map::new())
}

fn strip_markdown_code_block(text: &str) -> String {
    let trimmed = text.trim();
    // Check for ``` fence
    if let Some(start) = trimmed.find("```") {
        // find the next ``` after the opening fence
        let after_open = start + 3;
        // skip optional language identifier (e.g. "json")
        let content_start = trimmed[after_open..]
            .find('\n')
            .map(|nl| after_open + nl + 1)
            .unwrap_or(after_open);
        if let Some(end_rel) = trimmed[content_start..].find("```") {
            return trimmed[content_start..content_start + end_rel].to_string();
        }
    }
    trimmed.to_string()
}

// ---------------------------------------------------------------------------
// Helper: build UserInfo from JSON value
// ---------------------------------------------------------------------------

fn build_user_info_from_json(u: &Value, user_id: &str, domain: &str) -> Result<UserInfo> {
    // If already has nested profile structure
    if let Some(profile_val) = u.get("profile") {
        let name_val = profile_val.get("name");
        let display_name = name_val
            .and_then(|n| n.get("display_name"))
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown User")
            .to_string();
        let first_name = name_val
            .and_then(|n| n.get("first_name"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let last_name = name_val
            .and_then(|n| n.get("last_name"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let nickname = name_val
            .and_then(|n| n.get("nickname"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let email = profile_val
            .get("email")
            .and_then(|v| v.as_str())
            .unwrap_or(&format!("{}@{}", user_id, domain))
            .to_string();

        let profile = UserProfile {
            email,
            name: UserName {
                display_name,
                first_name,
                last_name,
                nickname,
            },
            manager_id: profile_val
                .get("manager_id")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
            skip_manager_id: None,
            department: profile_val
                .get("department")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
            skills: profile_val
                .get("skills")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_default(),
            title: profile_val
                .get("title")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
            location: profile_val
                .get("location")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
            timezone: profile_val
                .get("timezone")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
        };

        let groups: Vec<String> = u
            .get("groups")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        return Ok(UserInfo {
            id: user_id.to_string(),
            username: user_id.to_string(),
            groups,
            profile,
        });
    }

    // Flat structure – reshape into nested profile
    let display_name = u
        .get("name")
        .and_then(|n| {
            if let Some(dn) = n.get("display_name") {
                dn.as_str().map(|s| s.to_string())
            } else {
                n.as_str().map(|s| s.to_string())
            }
        })
        .unwrap_or_else(|| "Unknown User".to_string());

    let first_name = u
        .get("name")
        .and_then(|n| n.get("first_name"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let last_name = u
        .get("name")
        .and_then(|n| n.get("last_name"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let email = u
        .get("email")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| format!("{}@{}", user_id, domain));

    let profile = UserProfile {
        email,
        name: UserName {
            display_name,
            first_name,
            last_name,
            nickname: None,
        },
        manager_id: u
            .get("manager_id")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        skip_manager_id: None,
        department: u
            .get("department")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        skills: u
            .get("skills")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default(),
        title: u
            .get("title")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
        location: u
            .get("location")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .or_else(|| Some(DEFAULT_LOCATION.to_string())),
        timezone: u
            .get("timezone")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .or_else(|| Some(DEFAULT_TIMEZONE.to_string())),
    };

    let groups: Vec<String> = u
        .get("groups")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();

    Ok(UserInfo {
        id: user_id.to_string(),
        username: user_id.to_string(),
        groups,
        profile,
    })
}

// ---------------------------------------------------------------------------
// Helper: append a YAML-serialisable item to a YAML list file
// ---------------------------------------------------------------------------

/// Append a single serialisable item to a YAML list file.
///
/// If the file contains only `[]`, it is replaced with a one-element list.
/// Otherwise the serialised item is appended as YAML.
pub fn append_to_yaml<T: serde::Serialize>(item: &T, path: &str) -> Result<()> {
    let data = serde_json::to_value(item)?;
    let yaml_str = serde_yaml::to_string(&vec![data])
        .with_context(|| format!("serialising item to YAML for {}", path))?;

    if Path::new(path).exists() {
        let content = fs::read_to_string(path)?;
        let trimmed = content.trim();
        if trimmed == "[]" || trimmed.is_empty() {
            fs::write(path, &yaml_str)?;
        } else {
            let mut f = fs::OpenOptions::new().append(true).open(path)?;
            use std::io::Write;
            write!(f, "{}", yaml_str)?;
        }
    } else {
        fs::write(path, &yaml_str)?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// DataGenerator
// ---------------------------------------------------------------------------

/// LLM-driven synthetic data generator for EABench tenants.
///
/// Mirrors `DataGenerator` in `src/generator/pipeline.py`.
pub struct DataGenerator {
    /// The LLM provider used for all generation calls.
    pub llm: Box<dyn LLMProvider>,
    /// Root output directory where tenant folders are created.
    pub output_dir: String,
    /// Prompt templates keyed by prompt name.
    pub prompts: HashMap<String, String>,
}

impl DataGenerator {
    /// Create a new `DataGenerator` by loading prompt templates from a YAML
    /// file.
    pub fn new(
        llm: Box<dyn LLMProvider>,
        output_dir: impl Into<String>,
        prompts_path: &str,
    ) -> Result<Self> {
        let prompts = load_prompts(prompts_path)
            .with_context(|| format!("loading prompts from {}", prompts_path))?;
        Ok(DataGenerator {
            llm,
            output_dir: output_dir.into(),
            prompts,
        })
    }

    /// Create a new `DataGenerator` with pre-loaded prompt templates.
    pub fn with_prompts(
        llm: Box<dyn LLMProvider>,
        output_dir: impl Into<String>,
        prompts: HashMap<String, String>,
    ) -> Self {
        DataGenerator {
            llm,
            output_dir: output_dir.into(),
            prompts,
        }
    }

    // -----------------------------------------------------------------------
    // Public entry point
    // -----------------------------------------------------------------------

    /// Generate a full synthetic tenant directory.
    ///
    /// Creates the directory structure, generates users, then runs the daily
    /// simulation loop (emails, chats, meetings, files), and finally produces
    /// an evaluation dataset.
    pub fn generate_tenant(&self, story: &StoryConfig) -> Result<GenerationOutput> {
        let tenant_id = format!(
            "{}-{}",
            story.company_name.to_lowercase().replace(' ', "-"),
            Local::now().format("%Y%m%d")
        );
        let base_path = format!("{}/{}", self.output_dir, tenant_id);

        fs::create_dir_all(&base_path)
            .with_context(|| format!("creating tenant directory {}", base_path))?;
        fs::create_dir_all(format!("{}/config", base_path))?;
        fs::create_dir_all(format!("{}/docs", base_path))?;

        println!("Generating tenant: {}", tenant_id);

        // 1. Generate Users
        let users = self.generate_users(story, &tenant_id)?;

        if users.is_empty() {
            println!("Error: No users generated. Aborting.");
            return Ok(GenerationOutput {
                tenant_id,
                base_path,
                summary: "Failed to generate users. Check LLM output or prompts.".to_string(),
            });
        }

        // Save users to tenant.yaml
        let tenant_config = TenantConfig {
            id: tenant_id.clone(),
            domain: format!("{}.com", tenant_id),
            users: users.clone(),
            files_metadata: vec![],
            chats: vec![],
            group_chats: vec![],
            meetings: vec![],
            emails: vec![],
            channels: vec![],
            resource_limits: HashMap::new(),
            data_path: None,
            root_path: None,
        };

        let tenant_yaml = serde_yaml::to_string(&tenant_config)
            .context("serialising tenant config to YAML")?;
        fs::write(format!("{}/tenant.yaml", base_path), tenant_yaml)?;

        println!(
            "Users generated and saved to {}/tenant.yaml",
            base_path
        );

        // Initialise empty config files
        for config_file in &[
            "emails.yaml",
            "chats.yaml",
            "group_chats.yaml",
            "meetings.yaml",
            "files.yaml",
        ] {
            fs::write(format!("{}/config/{}", base_path, config_file), "[]\n")?;
        }

        // 2. Generate daily content
        self.generate_content(story, &users, &base_path, &tenant_id)?;

        Ok(GenerationOutput {
            tenant_id: tenant_id.clone(),
            base_path,
            summary: format!(
                "Generated tenant {} with users and content.",
                tenant_id
            ),
        })
    }

    // -----------------------------------------------------------------------
    // User generation
    // -----------------------------------------------------------------------

    /// Generate synthetic users in batches using the LLM.
    pub fn generate_users(
        &self,
        story: &StoryConfig,
        tenant_id: &str,
    ) -> Result<Vec<UserInfo>> {
        let total_users = story.num_users;
        let batch_size = story.eval_batch_size;
        let mut users: Vec<UserInfo> = Vec::new();
        let mut existing_ids: HashSet<String> = HashSet::new();

        let num_batches = (total_users + batch_size - 1) / batch_size;
        println!(
            "Generating {} users in {} batches (Batch Size: {})...",
            total_users, num_batches, batch_size
        );

        for i in 0..num_batches {
            let current_batch_size = batch_size.min(total_users - users.len());
            println!(
                "  Batch {}/{}: Generating {} users...",
                i + 1,
                num_batches,
                current_batch_size
            );

            let diversity_context = if users.is_empty() {
                "Focus on creating the core leadership team (C-level) and heads of key departments.".to_string()
            } else {
                let mut departments: HashMap<String, usize> = HashMap::new();
                for u in &users {
                    let dept = u
                        .profile
                        .department
                        .as_deref()
                        .unwrap_or("Unknown")
                        .to_string();
                    *departments.entry(dept).or_insert(0) += 1;
                }
                let dept_str: Vec<String> = departments
                    .iter()
                    .map(|(k, v)| format!("{}: {}", k, v))
                    .collect();
                let recent_names: Vec<String> = users
                    .iter()
                    .rev()
                    .take(10)
                    .map(|u| u.profile.name.display_name.clone())
                    .collect();

                format!(
                    "Current Department Distribution: {}.\nRecent Names (DO NOT REPEAT): {}.\n\
                     INSTRUCTIONS:\n\
                     1. Generate users for departments that are missing or understaffed.\n\
                     2. Add Individual Contributors (IC) to existing managers.\n\
                     3. CRITICAL: Ensure new user names are culturally diverse and NOT similar to existing ones.",
                    dept_str.join(", "),
                    recent_names.join(", ")
                )
            };

            let domain = format!("{}.com", tenant_id);
            let template = self
                .prompts
                .get("generate_users")
                .map(|s| s.as_str())
                .unwrap_or("");

            let prompt = if template.contains("{diversity_context}") {
                format_template(
                    template,
                    &[
                        ("company_name", &story.company_name),
                        ("industry", &story.industry),
                        ("company_size", &story.company_size),
                        ("description", &story.description),
                        ("domain", &domain),
                        ("num_users", &current_batch_size.to_string()),
                        ("diversity_context", &diversity_context),
                    ],
                )
            } else {
                let mut p = format_template(
                    template,
                    &[
                        ("company_name", &story.company_name),
                        ("industry", &story.industry),
                        ("company_size", &story.company_size),
                        ("description", &story.description),
                        ("domain", &domain),
                        ("num_users", &current_batch_size.to_string()),
                    ],
                );
                p.push_str(&format!("\n\n{}", diversity_context));
                p
            };

            let msgs = vec![{
                let mut m = HashMap::new();
                m.insert("role".to_string(), "user".to_string());
                m.insert("content".to_string(), prompt);
                m
            }];
            let response = self.llm.get_completion(&msgs)?;
            let data = parse_json(&response);

            let user_list: Vec<Value> = if let Some(arr) = data.as_array() {
                arr.clone()
            } else if let Some(obj) = data.as_object() {
                if let Some(Value::Array(arr)) = obj.get("users") {
                    arr.clone()
                } else {
                    vec![]
                }
            } else {
                vec![]
            };

            for u in user_list {
                let base_id = u
                    .get("id")
                    .or_else(|| u.get("username"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| {
                        let name = u
                            .get("name")
                            .and_then(|n| n.get("display_name"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("User");
                        name.to_lowercase()
                            .replace(' ', "")
                            .chars()
                            .take(8)
                            .collect()
                    });

                let mut user_id = base_id.clone();
                if existing_ids.contains(&user_id) {
                    user_id = format!("{}_{}", base_id, i + 1);
                }
                let mut counter = 1usize;
                while existing_ids.contains(&user_id) {
                    user_id = format!("{}_{}_{}", base_id, i + 1, counter);
                    counter += 1;
                }

                existing_ids.insert(user_id.clone());

                if let Ok(user_info) = build_user_info_from_json(&u, &user_id, &domain) {
                    users.push(user_info);
                }
            }
        }

        Ok(users)
    }

    // -----------------------------------------------------------------------
    // Daily content generation
    // -----------------------------------------------------------------------

    fn generate_content(
        &self,
        story: &StoryConfig,
        users: &[UserInfo],
        base_path: &str,
        tenant_id: &str,
    ) -> Result<()> {
        let users_context: String = users
            .iter()
            .map(|u| {
                format!(
                    "{}: {} ({})",
                    u.id,
                    u.profile.name.display_name,
                    u.profile.title.as_deref().unwrap_or("")
                )
            })
            .collect::<Vec<_>>()
            .join("\n");

        let start_date =
            Local::now().date_naive() - Duration::days(story.duration_days as i64);

        let mut long_history: Vec<String> = Vec::new();
        let mut recent_history: Vec<String> = Vec::new();
        let mut generation_log: Vec<Value> = Vec::new();

        for day in 0..story.duration_days {
            let current_date = start_date + Duration::days(day as i64);
            let date_str = current_date.format("%Y-%m-%d").to_string();
            println!(
                "Simulating Day {}/{}: {}",
                day + 1,
                story.duration_days,
                date_str
            );

            // Summarise history every 7 days
            if day > 0 && day % 7 == 0 {
                println!("Summarising history for week ending {}...", date_str);
                let template = self
                    .prompts
                    .get("summarize_history")
                    .map(|s| s.as_str())
                    .unwrap_or("");
                let prompt = format_template(
                    template,
                    &[("recent_events", &recent_history.join("\n"))],
                );
                let resp = self.llm_completion(&prompt)?;
                let data = parse_json(&resp);
                if let Some(s) = data.get("summary").and_then(|v| v.as_str()) {
                    if !s.is_empty() {
                        long_history.push(format!("[Week ending {}] {}", date_str, s));
                    }
                }
                recent_history.clear();
            }

            // 1. Generate daily story
            let template = self
                .prompts
                .get("generate_daily_story")
                .map(|s| s.as_str())
                .unwrap_or("");
            let prompt = format_template(
                template,
                &[
                    ("company_name", &story.company_name),
                    ("description", &story.description),
                    ("date", &date_str),
                    ("key_events", &story.key_events.join("\n")),
                    ("long_history", &long_history.join("\n")),
                    ("recent_history", &recent_history.join("\n")),
                ],
            );
            let resp = self.llm_completion(&prompt)?;
            let data = parse_json(&resp);
            let daily_events: Vec<String> = data
                .get("daily_events")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(|s| s.to_string()))
                        .collect()
                })
                .unwrap_or_default();

            if daily_events.is_empty() {
                println!("No events generated for {}", date_str);
                continue;
            }

            recent_history
                .extend(daily_events.iter().map(|e| format!("[{}] {}", date_str, e)));
            let current_scenario = daily_events.join("\n");

            generation_log.push(json!({
                "date": date_str,
                "type": "storyline",
                "events": daily_events
            }));

            let long_history_str = long_history.join("\n");
            let recent_history_str = recent_history.join("\n");

            // 2. Generate emails
            self.generate_emails_for_day(
                users,
                base_path,
                &date_str,
                &current_scenario,
                &long_history_str,
                &recent_history_str,
                &users_context,
                &mut generation_log,
            )?;

            // 3. Generate chats
            self.generate_chats_for_day(
                users,
                base_path,
                &date_str,
                &current_scenario,
                &long_history_str,
                &recent_history_str,
                &users_context,
                &mut generation_log,
            )?;

            // 4. Generate meetings
            self.generate_meetings_for_day(
                users,
                base_path,
                &date_str,
                &current_scenario,
                &long_history_str,
                &recent_history_str,
                &users_context,
                &mut generation_log,
            )?;

            // 5. Generate files
            self.generate_files_for_day(
                users,
                base_path,
                &date_str,
                &current_scenario,
                &long_history_str,
                &recent_history_str,
                &users_context,
                &mut generation_log,
            )?;
        }

        // Save generation log
        let log_json = serde_json::to_string_pretty(&generation_log)?;
        fs::write(format!("{}/generation_log.json", base_path), log_json)?;
        println!(
            "Generation log saved to {}/generation_log.json",
            base_path
        );

        // Generate evaluation dataset
        self.generate_eval_dataset(tenant_id, base_path, 200, story.eval_batch_size)?;

        Ok(())
    }

    // -----------------------------------------------------------------------
    // Per-day email generation
    // -----------------------------------------------------------------------

    fn generate_emails_for_day(
        &self,
        users: &[UserInfo],
        base_path: &str,
        date_str: &str,
        current_scenario: &str,
        long_history: &str,
        recent_history: &str,
        users_context: &str,
        generation_log: &mut Vec<Value>,
    ) -> Result<()> {
        let template = self
            .prompts
            .get("generate_email_summaries")
            .map(|s| s.as_str())
            .unwrap_or("");
        let prompt = format_template(
            template,
            &[
                ("event_description", current_scenario),
                ("long_history", long_history),
                ("recent_history", recent_history),
                ("users_context", users_context),
                ("date", date_str),
            ],
        );
        let resp = self.llm_completion(&prompt)?;
        let summaries = parse_json(&resp);

        let arr = match summaries.as_array() {
            Some(a) => a.clone(),
            None => return Ok(()),
        };

        for summary in &arr {
            if let Err(e) = self.generate_single_email(
                users,
                base_path,
                date_str,
                summary,
                long_history,
                recent_history,
                generation_log,
            ) {
                let id = summary.get("id").and_then(|v| v.as_str()).unwrap_or("?");
                println!("Error generating email {}: {}", id, e);
            }
        }
        Ok(())
    }

    fn generate_single_email(
        &self,
        users: &[UserInfo],
        base_path: &str,
        date_str: &str,
        summary: &Value,
        long_history: &str,
        recent_history: &str,
        generation_log: &mut Vec<Value>,
    ) -> Result<()> {
        let from_user_id = summary
            .get("from_user")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let from_user_obj = users.iter().find(|u| u.id == from_user_id);
        let from_name = from_user_obj
            .map(|u| u.profile.name.display_name.as_str())
            .unwrap_or("Unknown");
        let from_title = from_user_obj
            .and_then(|u| u.profile.title.as_deref())
            .unwrap_or("Unknown");

        let to_ids: Vec<&str> = summary
            .get("to_users")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect())
            .unwrap_or_default();
        let to_names: Vec<String> = to_ids
            .iter()
            .filter_map(|id| users.iter().find(|u| u.id == *id))
            .map(|u| u.profile.name.display_name.clone())
            .collect();

        let subject = summary
            .get("subject")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let context_summary = summary
            .get("context_summary")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let template = self
            .prompts
            .get("generate_email_content")
            .map(|s| s.as_str())
            .unwrap_or("");
        let content_prompt = format_template(
            template,
            &[
                ("subject", subject),
                ("from_user_name", from_name),
                ("from_user_title", from_title),
                ("to_users_names", &to_names.join(", ")),
                ("context_summary", context_summary),
                ("long_history", long_history),
                ("recent_history", recent_history),
            ],
        );
        let content_resp = self.llm_completion(&content_prompt)?;
        let content_data = parse_json(&content_resp);

        let email_id = summary
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let body = content_data
            .get("body")
            .and_then(|v| v.as_str())
            .unwrap_or("Content generation failed.")
            .to_string();
        let timestamp = summary
            .get("timestamp")
            .and_then(|v| v.as_str())
            .unwrap_or(date_str)
            .to_string();
        let cc_ids: Vec<String> = summary
            .get("cc_users")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        let email_obj = Email {
            id: email_id.clone(),
            from_user: from_user_id.to_string(),
            to_users: to_ids.iter().map(|s| s.to_string()).collect(),
            cc_users: cc_ids,
            bcc_users: vec![],
            subject: subject.to_string(),
            body: body.clone(),
            timestamp,
        };

        println!(
            "\n[Email] {} ({} chars)",
            email_obj.subject,
            email_obj.body.len()
        );
        if !email_obj.body.is_empty() {
            let preview: String = email_obj.body.chars().take(250).collect();
            println!("Body Preview: {}...", preview);
        }

        append_to_yaml(&email_obj, &format!("{}/config/emails.yaml", base_path))?;

        generation_log.push(json!({
            "date": date_str,
            "type": "email",
            "id": email_id,
            "subject": email_obj.subject,
            "from": email_obj.from_user,
            "to": email_obj.to_users,
            "cc": email_obj.cc_users,
            "body": body,
            "summary": context_summary
        }));
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Per-day chat generation
    // -----------------------------------------------------------------------

    fn generate_chats_for_day(
        &self,
        users: &[UserInfo],
        base_path: &str,
        date_str: &str,
        current_scenario: &str,
        long_history: &str,
        recent_history: &str,
        users_context: &str,
        generation_log: &mut Vec<Value>,
    ) -> Result<()> {
        let template = self
            .prompts
            .get("generate_chat_summaries")
            .map(|s| s.as_str())
            .unwrap_or("");
        let prompt = format_template(
            template,
            &[
                ("event_description", current_scenario),
                ("long_history", long_history),
                ("recent_history", recent_history),
                ("users_context", users_context),
                ("date", date_str),
            ],
        );
        let resp = self.llm_completion(&prompt)?;
        let summaries = parse_json(&resp);

        let arr = match summaries.as_array() {
            Some(a) => a.clone(),
            None => return Ok(()),
        };

        for summary in &arr {
            if let Err(e) = self.generate_single_chat(
                users,
                base_path,
                date_str,
                summary,
                long_history,
                recent_history,
                generation_log,
            ) {
                let id = summary.get("id").and_then(|v| v.as_str()).unwrap_or("?");
                println!("Error generating chat {}: {}", id, e);
            }
        }
        Ok(())
    }

    fn generate_single_chat(
        &self,
        users: &[UserInfo],
        base_path: &str,
        date_str: &str,
        summary: &Value,
        long_history: &str,
        recent_history: &str,
        generation_log: &mut Vec<Value>,
    ) -> Result<()> {
        let participants: Vec<&str> = summary
            .get("participants")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect())
            .unwrap_or_default();

        let participants_names: Vec<String> = participants
            .iter()
            .filter_map(|id| users.iter().find(|u| u.id == *id))
            .map(|u| u.profile.name.display_name.clone())
            .collect();

        let context_summary = summary
            .get("context_summary")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let template = self
            .prompts
            .get("generate_chat_content")
            .map(|s| s.as_str())
            .unwrap_or("");
        let content_prompt = format_template(
            template,
            &[
                ("participants_names", &participants_names.join(", ")),
                ("context_summary", context_summary),
                ("long_history", long_history),
                ("recent_history", recent_history),
                ("date", date_str),
            ],
        );
        let content_resp = self.llm_completion(&content_prompt)?;
        let content_data = parse_json(&content_resp);

        let is_direct = participants.len() == 2;
        let messages: Vec<ChatMessage> = content_data
            .get("messages")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|msg| {
                        let from_user = msg.get("from_user")?.as_str()?.to_string();
                        let to_user = if is_direct {
                            participants
                                .iter()
                                .find(|&&p| p != from_user)
                                .map(|s| s.to_string())
                        } else {
                            None
                        };
                        Some(ChatMessage {
                            from_user,
                            to_user,
                            content: msg
                                .get("content")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .to_string(),
                            timestamp: msg
                                .get("timestamp")
                                .and_then(|v| v.as_str())
                                .unwrap_or(date_str)
                                .to_string(),
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();

        let chat_type = summary
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("chat");
        let chat_id = summary
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        if chat_type == "group_chat" {
            let name = summary
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("Group Chat")
                .to_string();
            let group_chat = GroupChat {
                id: chat_id.clone(),
                name: name.clone(),
                participants: participants.iter().map(|s| s.to_string()).collect(),
                messages: messages.clone(),
            };
            println!("\n[Group Chat] {} ({} msgs)", name, messages.len());
            if let Some(m) = messages.first() {
                let preview: String = m.content.chars().take(250).collect();
                println!("First Msg: {}...", preview);
            }
            append_to_yaml(
                &group_chat,
                &format!("{}/config/group_chats.yaml", base_path),
            )?;
            generation_log.push(json!({
                "date": date_str,
                "type": "group_chat",
                "id": chat_id,
                "name": group_chat.name,
                "participants": group_chat.participants,
                "messages": messages,
                "summary": context_summary
            }));
        } else {
            let chat = Chat {
                id: chat_id.clone(),
                participants: participants.iter().map(|s| s.to_string()).collect(),
                messages: messages.clone(),
            };
            let p_str = chat.participants.join(", ");
            println!("\n[Chat] {} ({} msgs)", p_str, messages.len());
            if let Some(m) = messages.first() {
                let preview: String = m.content.chars().take(250).collect();
                println!("First Msg: {}...", preview);
            }
            append_to_yaml(&chat, &format!("{}/config/chats.yaml", base_path))?;
            generation_log.push(json!({
                "date": date_str,
                "type": "chat",
                "id": chat_id,
                "participants": chat.participants,
                "messages": messages,
                "summary": context_summary
            }));
        }
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Per-day meeting generation
    // -----------------------------------------------------------------------

    fn generate_meetings_for_day(
        &self,
        users: &[UserInfo],
        base_path: &str,
        date_str: &str,
        current_scenario: &str,
        long_history: &str,
        recent_history: &str,
        users_context: &str,
        generation_log: &mut Vec<Value>,
    ) -> Result<()> {
        let template = self
            .prompts
            .get("generate_meeting_summaries")
            .map(|s| s.as_str())
            .unwrap_or("");
        let prompt = format_template(
            template,
            &[
                ("event_description", current_scenario),
                ("long_history", long_history),
                ("recent_history", recent_history),
                ("users_context", users_context),
                ("date", date_str),
            ],
        );
        let resp = self.llm_completion(&prompt)?;
        let summaries = parse_json(&resp);

        let arr = match summaries.as_array() {
            Some(a) => a.clone(),
            None => return Ok(()),
        };

        for summary in &arr {
            if let Err(e) = self.generate_single_meeting(
                users,
                base_path,
                date_str,
                summary,
                long_history,
                recent_history,
                generation_log,
            ) {
                let id = summary.get("id").and_then(|v| v.as_str()).unwrap_or("?");
                println!("Error generating meeting {}: {}", id, e);
            }
        }
        Ok(())
    }

    fn generate_single_meeting(
        &self,
        users: &[UserInfo],
        base_path: &str,
        date_str: &str,
        summary: &Value,
        long_history: &str,
        recent_history: &str,
        generation_log: &mut Vec<Value>,
    ) -> Result<()> {
        let attendee_ids: Vec<&str> = summary
            .get("attendee_ids")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect())
            .unwrap_or_default();

        let participants_names: Vec<String> = attendee_ids
            .iter()
            .filter_map(|id| users.iter().find(|u| u.id == *id))
            .map(|u| u.profile.name.display_name.clone())
            .collect();

        let title = summary
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("Meeting");
        let agenda = summary
            .get("agenda")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let context_summary = summary
            .get("context_summary")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        // Generate transcript
        let transcript_template = self
            .prompts
            .get("generate_meeting_transcript")
            .map(|s| s.as_str())
            .unwrap_or("");
        let transcript_prompt = format_template(
            transcript_template,
            &[
                ("title", title),
                ("agenda", agenda),
                ("participants_names", &participants_names.join(", ")),
                ("context_summary", context_summary),
                ("long_history", long_history),
                ("recent_history", recent_history),
            ],
        );
        let transcript_resp = self.llm_completion(&transcript_prompt)?;
        let transcript_data = parse_json(&transcript_resp);

        let transcript_content = match transcript_data.get("transcript") {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Array(arr)) => arr
                .iter()
                .filter_map(|turn| {
                    if let Value::Object(obj) = turn {
                        let speaker = obj
                            .get("speaker")
                            .and_then(|v| v.as_str())
                            .unwrap_or("Unknown");
                        let text = obj
                            .get("content")
                            .or_else(|| obj.get("text"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        Some(format!("{}: {}", speaker, text))
                    } else if let Value::String(s) = turn {
                        Some(s.clone())
                    } else {
                        None
                    }
                })
                .collect::<Vec<_>>()
                .join("\n"),
            _ => "Transcript generation failed.".to_string(),
        };

        // Generate meeting chat
        let chat_template = self
            .prompts
            .get("generate_meeting_chat")
            .map(|s| s.as_str())
            .unwrap_or("");
        let chat_prompt = format_template(
            chat_template,
            &[
                ("title", title),
                ("participants_names", &participants_names.join(", ")),
                ("context_summary", context_summary),
                ("date", date_str),
            ],
        );
        let chat_resp = self.llm_completion(&chat_prompt)?;
        let chat_data = parse_json(&chat_resp);

        let meeting_chat_messages: Vec<ChatMessage> = chat_data
            .get("messages")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|msg| {
                        Some(ChatMessage {
                            from_user: msg.get("from_user")?.as_str()?.to_string(),
                            to_user: None,
                            content: msg
                                .get("content")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .to_string(),
                            timestamp: msg
                                .get("timestamp")
                                .and_then(|v| v.as_str())
                                .unwrap_or(date_str)
                                .to_string(),
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();

        let meeting_id = summary
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let organizer = attendee_ids.first().copied().unwrap_or("unknown").to_string();

        // Save meeting chat as a group chat
        let meeting_chat_obj = GroupChat {
            id: format!("chat_{}", meeting_id),
            name: format!("Chat: {}", title),
            participants: attendee_ids.iter().map(|s| s.to_string()).collect(),
            messages: meeting_chat_messages.clone(),
        };
        append_to_yaml(
            &meeting_chat_obj,
            &format!("{}/config/group_chats.yaml", base_path),
        )?;

        let meeting_obj = Meeting {
            id: meeting_id.clone(),
            title: title.to_string(),
            organizer,
            invitees: attendee_ids.iter().map(|s| s.to_string()).collect(),
            attendees: attendee_ids.iter().map(|s| s.to_string()).collect(),
            start_time: summary
                .get("start_time")
                .and_then(|v| v.as_str())
                .unwrap_or(&format!("{}T09:00:00", date_str))
                .to_string(),
            end_time: summary
                .get("end_time")
                .and_then(|v| v.as_str())
                .unwrap_or(&format!("{}T10:00:00", date_str))
                .to_string(),
            agenda: agenda.to_string(),
            location: summary
                .get("location")
                .and_then(|v| v.as_str())
                .unwrap_or("Online")
                .to_string(),
            transcript: Some(transcript_content.clone()),
        };

        println!("\n[Meeting] {}", meeting_obj.title);
        let preview: String = transcript_content.chars().take(250).collect();
        println!("Transcript Preview: {}...", preview);
        println!("Chat Preview: {} messages", meeting_chat_messages.len());

        append_to_yaml(&meeting_obj, &format!("{}/config/meetings.yaml", base_path))?;

        generation_log.push(json!({
            "date": date_str,
            "type": "meeting",
            "id": meeting_id,
            "title": meeting_obj.title,
            "organizer": meeting_obj.organizer,
            "attendees": meeting_obj.attendees,
            "transcript": transcript_content,
            "chat_messages": meeting_chat_messages,
            "summary": context_summary
        }));
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Per-day file generation
    // -----------------------------------------------------------------------

    fn generate_files_for_day(
        &self,
        users: &[UserInfo],
        base_path: &str,
        date_str: &str,
        current_scenario: &str,
        long_history: &str,
        recent_history: &str,
        users_context: &str,
        generation_log: &mut Vec<Value>,
    ) -> Result<()> {
        let template = self
            .prompts
            .get("generate_file_summaries")
            .map(|s| s.as_str())
            .unwrap_or("");
        let prompt = format_template(
            template,
            &[
                ("event_description", current_scenario),
                ("long_history", long_history),
                ("recent_history", recent_history),
                ("users_context", users_context),
                ("date", date_str),
            ],
        );
        let resp = self.llm_completion(&prompt)?;
        let summaries = parse_json(&resp);

        let arr = match summaries.as_array() {
            Some(a) => a.clone(),
            None => return Ok(()),
        };

        for summary in &arr {
            if let Err(e) = self.generate_single_file(
                users,
                base_path,
                date_str,
                summary,
                long_history,
                recent_history,
                generation_log,
            ) {
                let path = summary.get("path").and_then(|v| v.as_str()).unwrap_or("?");
                println!("Error generating file {}: {}", path, e);
            }
        }
        Ok(())
    }

    fn generate_single_file(
        &self,
        users: &[UserInfo],
        base_path: &str,
        date_str: &str,
        summary: &Value,
        long_history: &str,
        recent_history: &str,
        generation_log: &mut Vec<Value>,
    ) -> Result<()> {
        let created_by = summary
            .get("created_by")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let author_obj = users.iter().find(|u| u.id == created_by);
        let author_name = author_obj
            .map(|u| u.profile.name.display_name.as_str())
            .unwrap_or("Unknown");
        let context_summary = summary
            .get("context_summary")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let raw_path = summary
            .get("path")
            .and_then(|v| v.as_str())
            .unwrap_or("data/unknown.txt");
        let path = if raw_path.starts_with("data/") {
            raw_path.to_string()
        } else {
            format!("data/{}", raw_path)
        };

        // Retry logic
        let mut content = String::new();
        for attempt in 0..3 {
            let template = self
                .prompts
                .get("generate_file_content")
                .map(|s| s.as_str())
                .unwrap_or("");
            let content_prompt = format_template(
                template,
                &[
                    ("path", &path),
                    ("author_name", author_name),
                    ("context_summary", context_summary),
                    ("long_history", long_history),
                    ("recent_history", recent_history),
                ],
            );
            match self.llm_completion(&content_prompt) {
                Ok(resp) => {
                    let data = parse_json(&resp);
                    if let Some(c) = data.get("content").and_then(|v| v.as_str()) {
                        if !c.is_empty() {
                            content = c.to_string();
                            break;
                        }
                    }
                }
                Err(e) => println!("Attempt {} failed for file {}: {}", attempt + 1, path, e),
            }
        }
        if content.is_empty() {
            content = "Content generation failed.".to_string();
        }

        // Write file content
        let file_path = format!("{}/{}", base_path, path);
        if let Some(parent) = Path::new(&file_path).parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&file_path, &content)?;

        println!("\n[File] {}", path);
        let preview: String = content.chars().take(250).collect();
        println!("Content Preview: {}...", preview);

        // Save metadata
        let meta = FileMetadata {
            path: path.clone(),
            created_by: Some(created_by.to_string()),
            created_time: Some(Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()),
            last_modified_by: None,
            last_modified_time: None,
            snippet: summary
                .get("snippet")
                .or_else(|| summary.get("context_summary"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string()),
        };
        append_to_yaml(&meta, &format!("{}/config/files.yaml", base_path))?;

        generation_log.push(json!({
            "date": date_str,
            "type": "file",
            "path": path,
            "created_by": created_by,
            "content": content,
            "summary": context_summary
        }));
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Evaluation dataset generation
    // -----------------------------------------------------------------------

    /// Generate an evaluation dataset from the generation log.
    ///
    /// Produces both a JSON log (with reasoning) and a YAML eval set
    /// (without reasoning).
    pub fn generate_eval_dataset(
        &self,
        tenant_id: &str,
        base_path: &str,
        num_queries: usize,
        batch_size: usize,
    ) -> Result<()> {
        println!("Generating evaluation dataset for {}...", tenant_id);

        let log_path = format!("{}/generation_log.json", base_path);
        if !Path::new(&log_path).exists() {
            println!("Error: Generation log not found at {}", log_path);
            return Ok(());
        }

        let log_raw = fs::read_to_string(&log_path)?;
        let generation_log: Vec<Value> = serde_json::from_str(&log_raw)?;

        // Load users context
        let tenant_path = format!("{}/tenant.yaml", base_path);
        let users_context = if Path::new(&tenant_path).exists() {
            let raw = fs::read_to_string(&tenant_path)?;
            let data: Value = serde_yaml::from_str(&raw).unwrap_or(Value::Null);
            data.get("users")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|u| {
                            let id = u.get("id")?.as_str()?;
                            let dn = u
                                .get("profile")
                                .and_then(|p| p.get("name"))
                                .and_then(|n| n.get("display_name"))
                                .and_then(|v| v.as_str())
                                .unwrap_or(id);
                            Some(format!("{} ({})", id, dn))
                        })
                        .collect::<Vec<_>>()
                        .join(", ")
                })
                .unwrap_or_default()
        } else {
            String::new()
        };

        let emails: Vec<&Value> = generation_log
            .iter()
            .filter(|x| x.get("type").and_then(|v| v.as_str()) == Some("email"))
            .collect();
        let meetings: Vec<&Value> = generation_log
            .iter()
            .filter(|x| x.get("type").and_then(|v| v.as_str()) == Some("meeting"))
            .collect();
        let files: Vec<&Value> = generation_log
            .iter()
            .filter(|x| x.get("type").and_then(|v| v.as_str()) == Some("file"))
            .collect();
        let chats: Vec<&Value> = generation_log
            .iter()
            .filter(|x| {
                matches!(
                    x.get("type").and_then(|v| v.as_str()),
                    Some("chat") | Some("group_chat")
                )
            })
            .collect();
        let storyline: Vec<&Value> = generation_log
            .iter()
            .filter(|x| x.get("type").and_then(|v| v.as_str()) == Some("storyline"))
            .collect();

        let mut eval_dataset: Vec<Value> = Vec::new();

        // 1. Search queries (~40%)
        let num_search = (num_queries as f64 * 0.4) as usize;
        println!("Generating {} search queries...", num_search);
        let all_items: Vec<&Value> = emails
            .iter()
            .chain(meetings.iter())
            .chain(files.iter())
            .chain(chats.iter())
            .copied()
            .collect();
        // Stable deterministic order (no shuffle to keep tests deterministic)
        for chunk in all_items.chunks(batch_size) {
            if eval_dataset.len() >= num_search {
                break;
            }
            let items_context: Vec<Value> = chunk
                .iter()
                .map(|item| {
                    let mut ctx = json!({
                        "id": item.get("id").or_else(|| item.get("path")),
                        "type": item.get("type"),
                        "date": item.get("date"),
                        "summary": item.get("summary").unwrap_or(&Value::String(String::new()))
                    });
                    match item.get("type").and_then(|v| v.as_str()) {
                        Some("email") => {
                            ctx["from"] = item.get("from").cloned().unwrap_or(Value::Null);
                            ctx["subject"] = item.get("subject").cloned().unwrap_or(Value::Null);
                        }
                        Some("meeting") => {
                            ctx["title"] = item.get("title").cloned().unwrap_or(Value::Null);
                            ctx["attendees"] = item.get("attendees").cloned().unwrap_or(Value::Null);
                        }
                        Some("file") => {
                            ctx["path"] = item.get("path").cloned().unwrap_or(Value::Null);
                            ctx["created_by"] =
                                item.get("created_by").cloned().unwrap_or(Value::Null);
                        }
                        _ => {}
                    }
                    ctx
                })
                .collect();

            let template = self
                .prompts
                .get("generate_search_eval")
                .map(|s| s.as_str())
                .unwrap_or("");
            let prompt = format_template(
                template,
                &[
                    ("num", "5"),
                    (
                        "items_context",
                        &serde_json::to_string_pretty(&items_context).unwrap_or_default(),
                    ),
                    ("users_context", &users_context),
                ],
            );
            let resp = self.llm_completion(&prompt)?;
            let queries = parse_json(&resp);
            if let Some(arr) = queries.as_array() {
                eval_dataset.extend(arr.iter().cloned());
            }
        }

        // 2. Multi-hop queries (~40%)
        let num_multihop = (num_queries as f64 * 0.4) as usize;
        println!("Generating {} multi-hop queries...", num_multihop);
        let mut events_by_date: HashMap<String, Vec<&Value>> = HashMap::new();
        for item in &generation_log {
            if item.get("type").and_then(|v| v.as_str()) == Some("storyline") {
                continue;
            }
            let d = item
                .get("date")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            events_by_date.entry(d).or_default().push(item);
        }
        let mut dates: Vec<String> = events_by_date.keys().cloned().collect();
        dates.sort();

        for d in &dates {
            let multihop_count = eval_dataset
                .iter()
                .filter(|q| q.get("type").and_then(|v| v.as_str()) == Some("multihop"))
                .count();
            if multihop_count >= num_multihop {
                break;
            }
            let day_events = &events_by_date[d];
            if day_events.len() < 2 {
                continue;
            }
            let events_context: Vec<Value> = day_events
                .iter()
                .map(|item| {
                    json!({
                        "id": item.get("id").or_else(|| item.get("path")),
                        "type": item.get("type"),
                        "summary": item.get("summary").unwrap_or(&Value::String(String::new()))
                    })
                })
                .collect();

            let template = self
                .prompts
                .get("generate_multihop_eval")
                .map(|s| s.as_str())
                .unwrap_or("");
            let prompt = format_template(
                template,
                &[
                    ("num", "3"),
                    (
                        "events_context",
                        &serde_json::to_string_pretty(&events_context).unwrap_or_default(),
                    ),
                    ("users_context", &users_context),
                ],
            );
            let resp = self.llm_completion(&prompt)?;
            let queries = parse_json(&resp);
            if let Some(arr) = queries.as_array() {
                for q in arr {
                    let mut q = q.clone();
                    q["type"] = Value::String("multihop".to_string());
                    eval_dataset.push(q);
                }
            }
        }

        // 3. Report queries (~20%)
        let num_report = (num_queries as f64 * 0.2) as usize;
        println!("Generating {} report queries...", num_report);
        let mut artifacts_by_date: HashMap<String, Vec<&Value>> = HashMap::new();
        for item in &generation_log {
            if item.get("type").and_then(|v| v.as_str()) == Some("storyline") {
                continue;
            }
            let d = item
                .get("date")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            artifacts_by_date.entry(d).or_default().push(item);
        }

        let mut sorted_storyline: Vec<&Value> = storyline.clone();
        sorted_storyline.sort_by_key(|x| x.get("date").and_then(|v| v.as_str()).unwrap_or(""));

        let mut generated_reports = 0usize;
        let max_attempts = num_report * 2;
        let window_size = 3usize;

        for attempt in 0..max_attempts {
            if generated_reports >= num_report || sorted_storyline.is_empty() {
                break;
            }
            let start_idx = attempt % sorted_storyline.len().max(1);
            let window: Vec<&Value> = sorted_storyline
                .iter()
                .skip(start_idx)
                .take(window_size)
                .copied()
                .collect();

            let story_context: Vec<String> = window
                .iter()
                .map(|item| {
                    let date = item.get("date").and_then(|v| v.as_str()).unwrap_or("");
                    let events = item
                        .get("events")
                        .and_then(|v| v.as_array())
                        .map(|arr| {
                            arr.iter()
                                .filter_map(|v| v.as_str())
                                .collect::<Vec<_>>()
                                .join(", ")
                        })
                        .unwrap_or_default();
                    let day_artifacts = artifacts_by_date.get(date).map(|v| v.as_slice()).unwrap_or(&[]);
                    let artifacts_str = if day_artifacts.is_empty() {
                        String::new()
                    } else {
                        let list: Vec<String> = day_artifacts
                            .iter()
                            .map(|art| {
                                let id = art.get("id").or_else(|| art.get("path"))
                                    .and_then(|v| v.as_str()).unwrap_or("?");
                                let t = art.get("type").and_then(|v| v.as_str()).unwrap_or("?");
                                let s = art.get("summary").and_then(|v| v.as_str()).unwrap_or("No summary");
                                format!("- [{}] {}: {}", t, id, s)
                            })
                            .collect();
                        format!("\nArtifacts:\n{}", list.join("\n"))
                    };
                    format!("Date: {}\nEvents: {}{}", date, events, artifacts_str)
                })
                .collect();

            let batch_num = 3usize.min(num_report - generated_reports);
            let template = self
                .prompts
                .get("generate_report_eval")
                .map(|s| s.as_str())
                .unwrap_or("");
            let prompt = format_template(
                template,
                &[
                    ("num", &batch_num.to_string()),
                    ("context", &story_context.join("\n\n")),
                    ("users_context", &users_context),
                ],
            );
            let resp = self.llm_completion(&prompt)?;
            let queries = parse_json(&resp);
            if let Some(arr) = queries.as_array() {
                for q in arr {
                    let mut q = q.clone();
                    q["type"] = Value::String("report".to_string());
                    eval_dataset.push(q);
                    generated_reports += 1;
                    if generated_reports >= num_report {
                        break;
                    }
                }
            }
        }

        // Post-process: assign IDs and normalise assertions
        let final_cases: Vec<Value> = eval_dataset
            .iter()
            .enumerate()
            .map(|(i, case)| {
                let assertions: Vec<Value> = case
                    .get("assertions")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .map(|a| {
                                if a.is_string() {
                                    json!({ "description": a })
                                } else {
                                    a.clone()
                                }
                            })
                            .collect()
                    })
                    .unwrap_or_default();

                json!({
                    "id": format!("case_{:03}", i + 1),
                    "reasoning": case.get("reasoning").cloned().unwrap_or(Value::String(String::new())),
                    "query": case.get("query").cloned().unwrap_or(Value::Null),
                    "user_id": case.get("user_id").cloned().unwrap_or(Value::String("unknown".to_string())),
                    "assertions": assertions,
                    "entity_list": case.get("entity_list").cloned().unwrap_or(Value::Array(vec![]))
                })
            })
            .collect();

        let timestamp = Local::now().format("%Y%m%d_%H%M").to_string();

        // Save JSON log (with reasoning)
        let log_output = serde_json::to_string_pretty(&final_cases)?;
        let log_path = format!("{}/eval_dataset_log_{}.json", base_path, timestamp);
        fs::write(&log_path, log_output)?;
        println!("Evaluation dataset log saved to {}", log_path);

        // Save YAML (without reasoning)
        let yaml_cases: Vec<Value> = final_cases
            .iter()
            .map(|case| {
                let mut c = case.clone();
                if let Some(obj) = c.as_object_mut() {
                    obj.remove("reasoning");
                }
                c
            })
            .collect();

        let eval_data = json!({
            "name": format!("Evaluation Set for {}", tenant_id),
            "description": "Generated evaluation queries covering search, multi-hop reasoning, and report generation.",
            "cases": yaml_cases
        });

        let yaml_str = serde_yaml::to_string(&eval_data)?;
        let yaml_path = format!("{}/eval_dataset_{}.yaml", base_path, timestamp);
        fs::write(&yaml_path, yaml_str)?;

        println!(
            "Generated {} evaluation queries. Saved to {}",
            final_cases.len(),
            yaml_path
        );
        Ok(())
    }

    // -----------------------------------------------------------------------
    // Private helper
    // -----------------------------------------------------------------------

    fn llm_completion(&self, prompt: &str) -> Result<String> {
        let mut m = HashMap::new();
        m.insert("role".to_string(), "user".to_string());
        m.insert("content".to_string(), prompt.to_string());
        self.llm.get_completion(&[m])
    }
}

// ---------------------------------------------------------------------------
// Prompt loader
// ---------------------------------------------------------------------------

fn load_prompts(path: &str) -> Result<HashMap<String, String>> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("reading prompts file {}", path))?;
    let raw_map: HashMap<String, Value> = serde_yaml::from_str(&raw)
        .with_context(|| format!("parsing prompts YAML from {}", path))?;
    Ok(raw_map
        .into_iter()
        .filter_map(|(k, v)| v.as_str().map(|s| (k, s.to_string())))
        .collect())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::generator::llm_provider::{LLMProvider, LLMResponse, Message};
    use crate::generator::models::StoryConfig;
    use tempfile::TempDir;

    // -----------------------------------------------------------------------
    // format_template tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_format_template_basic_substitution() {
        let result = format_template("Hello {name}!", &[("name", "World")]);
        assert_eq!(result, "Hello World!");
    }

    #[test]
    fn test_format_template_multiple_vars() {
        let result = format_template(
            "{company} is in {industry}",
            &[("company", "Acme"), ("industry", "Software")],
        );
        assert_eq!(result, "Acme is in Software");
    }

    #[test]
    fn test_format_template_double_braces_converted() {
        let result = format_template(
            "Output: {{\"key\": \"{val}\"}}",
            &[("val", "hello")],
        );
        assert_eq!(result, "Output: {\"key\": \"hello\"}");
    }

    #[test]
    fn test_format_template_no_vars() {
        let result = format_template("No vars here", &[]);
        assert_eq!(result, "No vars here");
    }

    #[test]
    fn test_format_template_repeated_var() {
        let result = format_template("{x} + {x}", &[("x", "1")]);
        assert_eq!(result, "1 + 1");
    }

    // -----------------------------------------------------------------------
    // parse_json tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_parse_json_plain_list() {
        let v = parse_json(r#"[{"id": "a"}, {"id": "b"}]"#);
        assert!(v.is_array());
        assert_eq!(v.as_array().unwrap().len(), 2);
    }

    #[test]
    fn test_parse_json_plain_object() {
        let v = parse_json(r#"{"key": "value"}"#);
        assert_eq!(v.get("key").and_then(|v| v.as_str()), Some("value"));
    }

    #[test]
    fn test_parse_json_markdown_code_block() {
        let v = parse_json("```json\n{\"users\": []}\n```");
        assert!(v.get("users").is_some());
    }

    #[test]
    fn test_parse_json_markdown_block_no_lang() {
        let v = parse_json("```\n{\"result\": 42}\n```");
        assert_eq!(v.get("result").and_then(|v| v.as_i64()), Some(42));
    }

    #[test]
    fn test_parse_json_with_preamble_text() {
        let v = parse_json("Here is the JSON:\n{\"answer\": true}");
        assert_eq!(v.get("answer").and_then(|v| v.as_bool()), Some(true));
    }

    #[test]
    fn test_parse_json_list_with_preamble() {
        let v = parse_json("Sure! [1, 2, 3]");
        assert!(v.is_array());
        assert_eq!(v.as_array().unwrap().len(), 3);
    }

    #[test]
    fn test_parse_json_invalid_returns_empty_object() {
        let v = parse_json("not valid json at all");
        assert!(v.is_object());
        assert!(v.as_object().unwrap().is_empty());
    }

    #[test]
    fn test_parse_json_empty_string_returns_empty_object() {
        let v = parse_json("");
        assert!(v.is_object());
    }

    #[test]
    fn test_parse_json_nested_structure() {
        let v = parse_json(r#"{"users": [{"id": "u1", "name": "Alice"}]}"#);
        let users = v.get("users").unwrap().as_array().unwrap();
        assert_eq!(users.len(), 1);
        assert_eq!(users[0].get("id").and_then(|v| v.as_str()), Some("u1"));
    }

    // -----------------------------------------------------------------------
    // append_to_yaml tests
    // -----------------------------------------------------------------------

    #[test]
    fn test_append_to_yaml_creates_new_file() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("test.yaml").to_str().unwrap().to_string();
        let item = serde_json::json!({"id": "e1", "subject": "Hello"});
        append_to_yaml(&item, &path).unwrap();
        assert!(std::path::Path::new(&path).exists());
        let content = fs::read_to_string(&path).unwrap();
        assert!(content.contains("e1") || content.contains("Hello"));
    }

    #[test]
    fn test_append_to_yaml_replaces_empty_list() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("test.yaml").to_str().unwrap().to_string();
        fs::write(&path, "[]\n").unwrap();
        let item = serde_json::json!({"id": "e1"});
        append_to_yaml(&item, &path).unwrap();
        let content = fs::read_to_string(&path).unwrap();
        assert!(content.contains("e1"));
        assert!(!content.starts_with("[]"));
    }

    #[test]
    fn test_append_to_yaml_appends_to_existing() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("test.yaml").to_str().unwrap().to_string();
        let item1 = serde_json::json!({"id": "e1"});
        let item2 = serde_json::json!({"id": "e2"});
        append_to_yaml(&item1, &path).unwrap();
        append_to_yaml(&item2, &path).unwrap();
        let content = fs::read_to_string(&path).unwrap();
        assert!(content.contains("e1"));
        assert!(content.contains("e2"));
    }

    // -----------------------------------------------------------------------
    // DataGenerator construction tests
    // -----------------------------------------------------------------------

    fn make_minimal_prompts() -> HashMap<String, String> {
        let mut p = HashMap::new();
        p.insert(
            "generate_users".to_string(),
            "Generate users for {company_name} in {industry} (size: {company_size}). {diversity_context} domain: {domain} num_users: {num_users}".to_string(),
        );
        p.insert(
            "generate_daily_story".to_string(),
            "Daily events for {company_name} on {date}. key_events: {key_events} long_history: {long_history} recent_history: {recent_history} description: {description}".to_string(),
        );
        p.insert(
            "generate_email_summaries".to_string(),
            "Emails for {date}: {event_description} long: {long_history} recent: {recent_history} users: {users_context}".to_string(),
        );
        p.insert(
            "generate_email_content".to_string(),
            "Email body for subject {subject} from {from_user_name} ({from_user_title}) to {to_users_names}. context: {context_summary} long: {long_history} recent: {recent_history}".to_string(),
        );
        p.insert(
            "generate_chat_summaries".to_string(),
            "Chats for {date}: {event_description} long: {long_history} recent: {recent_history} users: {users_context}".to_string(),
        );
        p.insert(
            "generate_chat_content".to_string(),
            "Chat for participants {participants_names}: {context_summary} long: {long_history} recent: {recent_history} date: {date}".to_string(),
        );
        p.insert(
            "generate_meeting_summaries".to_string(),
            "Meetings for {date}: {event_description} long: {long_history} recent: {recent_history} users: {users_context}".to_string(),
        );
        p.insert(
            "generate_meeting_transcript".to_string(),
            "Transcript for {title} ({agenda}) with {participants_names}: {context_summary} long: {long_history} recent: {recent_history}".to_string(),
        );
        p.insert(
            "generate_meeting_chat".to_string(),
            "Meeting chat for {title} with {participants_names}: {context_summary} date: {date}".to_string(),
        );
        p.insert(
            "generate_file_summaries".to_string(),
            "Files for {date}: {event_description} long: {long_history} recent: {recent_history} users: {users_context}".to_string(),
        );
        p.insert(
            "generate_file_content".to_string(),
            "Content of file {path} by {author_name}: {context_summary} long: {long_history} recent: {recent_history}".to_string(),
        );
        p.insert(
            "summarize_history".to_string(),
            "Summarize: {recent_events}".to_string(),
        );
        p.insert(
            "generate_search_eval".to_string(),
            "Search eval: users: {users_context} items: {items_context} num: {num}".to_string(),
        );
        p.insert(
            "generate_multihop_eval".to_string(),
            "Multi-hop: users: {users_context} events: {events_context} num: {num}".to_string(),
        );
        p.insert(
            "generate_report_eval".to_string(),
            "Report: users: {users_context} context: {context} num: {num}".to_string(),
        );
        p
    }

    /// A smart mock provider that returns appropriate JSON for each pipeline stage.
    struct PipelineMockProvider;

    impl LLMProvider for PipelineMockProvider {
        fn generate(
            &self,
            history: &[Message],
            _tools: &[serde_json::Value],
        ) -> anyhow::Result<LLMResponse> {
            let content = history
                .last()
                .and_then(|m| m.content.as_deref())
                .unwrap_or("");
            Ok(LLMResponse {
                content: Some(self.respond(content)),
                tool_calls: None,
                usage: None,
            })
        }

        fn get_completion(
            &self,
            messages: &[HashMap<String, String>],
        ) -> anyhow::Result<String> {
            let content = messages
                .last()
                .and_then(|m| m.get("content"))
                .map(|s| s.as_str())
                .unwrap_or("");
            Ok(self.respond(content))
        }
    }

    impl PipelineMockProvider {
        fn respond(&self, prompt: &str) -> String {
            let lp = prompt.to_lowercase();

            // Users
            if lp.contains("generate users") || lp.contains("num_users") {
                return serde_json::json!({
                    "users": [{
                        "id": "user1",
                        "username": "user1",
                        "groups": ["Engineering"],
                        "profile": {
                            "email": "user1@test.com",
                            "name": {"display_name": "Test User", "first_name": "Test", "last_name": "User"},
                            "title": "Engineer",
                            "department": "Engineering",
                            "skills": [],
                            "location": "San Francisco",
                            "timezone": "America/Los_Angeles"
                        }
                    }]
                })
                .to_string();
            }
            // Daily story
            if lp.contains("daily events") || lp.contains("key_events") {
                return serde_json::json!({
                    "daily_events": ["Standup meeting", "Code review session"]
                })
                .to_string();
            }
            // Email summaries
            if lp.contains("emails for") {
                return serde_json::json!([{
                    "id": "email_1",
                    "from_user": "user1",
                    "to_users": ["user1"],
                    "cc_users": [],
                    "subject": "Test Email",
                    "context_summary": "A test email",
                    "timestamp": "2025-01-01T09:00:00"
                }])
                .to_string();
            }
            // Email content
            if lp.contains("email body for subject") {
                return serde_json::json!({"body": "Dear Team,\n\nThis is a test email.\n\nBest,\nTest User"}).to_string();
            }
            // Chat summaries
            if lp.contains("chats for") {
                return serde_json::json!([{
                    "type": "chat",
                    "id": "chat_1",
                    "name": "Test Chat",
                    "participants": ["user1"],
                    "context_summary": "A test chat"
                }])
                .to_string();
            }
            // Chat content
            if lp.contains("chat for participants") {
                return serde_json::json!({"messages": [{"from_user": "user1", "content": "Hello!", "timestamp": "2025-01-01T09:00:00"}]}).to_string();
            }
            // Meeting summaries
            if lp.contains("meetings for") {
                return serde_json::json!([{
                    "id": "meeting_1",
                    "title": "Test Meeting",
                    "organizer_id": "user1",
                    "attendee_ids": ["user1"],
                    "start_time": "2025-01-01T09:00:00",
                    "end_time": "2025-01-01T10:00:00",
                    "location": "Online",
                    "agenda": "Test agenda",
                    "context_summary": "A test meeting"
                }])
                .to_string();
            }
            // Meeting transcript
            if lp.contains("transcript for") {
                return serde_json::json!({"transcript": "User1: Hello everyone\nUser1: Let's get started"}).to_string();
            }
            // Meeting chat
            if lp.contains("meeting chat for") {
                return serde_json::json!({"messages": [{"from_user": "user1", "content": "Here is the link", "timestamp": "2025-01-01T09:05:00"}]}).to_string();
            }
            // File summaries
            if lp.contains("files for") {
                return serde_json::json!([{
                    "path": "data/docs/test.md",
                    "created_by": "user1",
                    "context_summary": "A test doc",
                    "snippet": "Test content preview"
                }])
                .to_string();
            }
            // File content
            if lp.contains("content of file") {
                return serde_json::json!({"content": "# Test Document\n\nThis is test content."}).to_string();
            }
            // History summary
            if lp.contains("summarize:") {
                return serde_json::json!({"summary": "Weekly summary of events."}).to_string();
            }
            // Eval: search
            if lp.contains("search eval") {
                return serde_json::json!([{
                    "reasoning": "r",
                    "query": "Find test file",
                    "user_id": "user1",
                    "assertions": ["Returns test.md"],
                    "entity_list": []
                }])
                .to_string();
            }
            // Eval: multi-hop
            if lp.contains("multi-hop") {
                return serde_json::json!([{
                    "reasoning": "r",
                    "query": "Who sent the email?",
                    "user_id": "user1",
                    "assertions": ["Identifies user1"],
                    "entity_list": []
                }])
                .to_string();
            }
            // Eval: report
            if lp.contains("report:") {
                return serde_json::json!([{
                    "reasoning": "r",
                    "query": "Summarize the week",
                    "user_id": "user1",
                    "assertions": ["Summary is provided"],
                    "entity_list": []
                }])
                .to_string();
            }

            // Default
            "{}".to_string()
        }
    }

    #[test]
    fn test_data_generator_construction_with_prompts() {
        let prompts = make_minimal_prompts();
        let gen = DataGenerator::with_prompts(
            Box::new(PipelineMockProvider),
            "/tmp/test-tenants",
            prompts,
        );
        assert_eq!(gen.output_dir, "/tmp/test-tenants");
        assert!(gen.prompts.contains_key("generate_users"));
    }

    #[test]
    fn test_generate_users_returns_users() {
        let prompts = make_minimal_prompts();
        let gen = DataGenerator::with_prompts(
            Box::new(PipelineMockProvider),
            "/tmp/test",
            prompts,
        );
        let story = StoryConfig {
            num_users: 1,
            eval_batch_size: 1,
            ..StoryConfig::new("Acme", "Software", "A test company")
        };
        let users = gen.generate_users(&story, "test-tenant-001").unwrap();
        assert!(!users.is_empty());
        assert_eq!(users[0].id, "user1");
    }

    #[test]
    fn test_generate_users_deduplicates_ids() {
        // Mock returns same user ID twice to test deduplication
        struct DupMock;
        impl LLMProvider for DupMock {
            fn generate(&self, _h: &[Message], _t: &[Value]) -> anyhow::Result<LLMResponse> {
                Ok(LLMResponse { content: Some(serde_json::json!({"users": [
                    {"id": "dup", "username": "dup", "groups": [], "profile": {"email": "dup@x.com", "name": {"display_name": "Dup User", "first_name": "Dup", "last_name": "User"}, "department": "Eng", "skills": [], "title": "E"}},
                    {"id": "dup", "username": "dup", "groups": [], "profile": {"email": "dup@x.com", "name": {"display_name": "Dup User2", "first_name": "Dup", "last_name": "User2"}, "department": "Eng", "skills": [], "title": "E"}}
                ]}).to_string()), tool_calls: None, usage: None })
            }
        }
        let prompts = make_minimal_prompts();
        let gen = DataGenerator::with_prompts(Box::new(DupMock), "/tmp/t", prompts);
        let story = StoryConfig {
            num_users: 2,
            eval_batch_size: 2,
            ..StoryConfig::new("T", "T", "T")
        };
        let users = gen.generate_users(&story, "test-tenant").unwrap();
        // Both users should be present with different IDs
        assert_eq!(users.len(), 2);
        let ids: Vec<&str> = users.iter().map(|u| u.id.as_str()).collect();
        assert_ne!(ids[0], ids[1]);
    }

    #[test]
    fn test_generate_tenant_creates_directory_structure() {
        let dir = TempDir::new().unwrap();
        let prompts = make_minimal_prompts();
        let gen = DataGenerator::with_prompts(
            Box::new(PipelineMockProvider),
            dir.path().to_str().unwrap(),
            prompts,
        );
        let story = StoryConfig {
            num_users: 1,
            eval_batch_size: 1,
            duration_days: 1,
            ..StoryConfig::new("TestCo", "Software", "A test company")
        };
        let output = gen.generate_tenant(&story).unwrap();
        assert!(!output.tenant_id.is_empty());
        assert!(std::path::Path::new(&output.base_path).exists());
        assert!(std::path::Path::new(&format!("{}/tenant.yaml", output.base_path)).exists());
        assert!(std::path::Path::new(&format!("{}/config", output.base_path)).exists());
    }

    #[test]
    fn test_generate_tenant_creates_config_files() {
        let dir = TempDir::new().unwrap();
        let prompts = make_minimal_prompts();
        let gen = DataGenerator::with_prompts(
            Box::new(PipelineMockProvider),
            dir.path().to_str().unwrap(),
            prompts,
        );
        let story = StoryConfig {
            num_users: 1,
            eval_batch_size: 1,
            duration_days: 1,
            ..StoryConfig::new("TestCo2", "Finance", "A finance company")
        };
        let output = gen.generate_tenant(&story).unwrap();
        for config_file in &["emails.yaml", "chats.yaml", "group_chats.yaml", "meetings.yaml", "files.yaml"] {
            let p = format!("{}/config/{}", output.base_path, config_file);
            assert!(std::path::Path::new(&p).exists(), "Missing config file: {}", config_file);
        }
    }

    #[test]
    fn test_generate_tenant_creates_generation_log() {
        let dir = TempDir::new().unwrap();
        let prompts = make_minimal_prompts();
        let gen = DataGenerator::with_prompts(
            Box::new(PipelineMockProvider),
            dir.path().to_str().unwrap(),
            prompts,
        );
        let story = StoryConfig {
            num_users: 1,
            eval_batch_size: 1,
            duration_days: 1,
            ..StoryConfig::new("TestCo3", "Retail", "A retail company")
        };
        let output = gen.generate_tenant(&story).unwrap();
        let log_path = format!("{}/generation_log.json", output.base_path);
        assert!(std::path::Path::new(&log_path).exists());
        let log_content = fs::read_to_string(&log_path).unwrap();
        let log: Vec<Value> = serde_json::from_str(&log_content).unwrap();
        // Should contain storyline events for 1 day
        assert!(!log.is_empty());
    }

    #[test]
    fn test_generate_tenant_output_has_tenant_id() {
        let dir = TempDir::new().unwrap();
        let prompts = make_minimal_prompts();
        let gen = DataGenerator::with_prompts(
            Box::new(PipelineMockProvider),
            dir.path().to_str().unwrap(),
            prompts,
        );
        let story = StoryConfig {
            num_users: 1,
            eval_batch_size: 1,
            duration_days: 1,
            ..StoryConfig::new("Acme Corp", "Tech", "A tech company")
        };
        let output = gen.generate_tenant(&story).unwrap();
        assert!(output.tenant_id.starts_with("acme-corp-"));
    }

    #[test]
    fn test_generate_tenant_with_no_users_returns_abort_message() {
        struct EmptyMock;
        impl LLMProvider for EmptyMock {
            fn generate(&self, _h: &[Message], _t: &[Value]) -> anyhow::Result<LLMResponse> {
                Ok(LLMResponse { content: Some("{}".to_string()), tool_calls: None, usage: None })
            }
        }
        let dir = TempDir::new().unwrap();
        let gen = DataGenerator::with_prompts(
            Box::new(EmptyMock),
            dir.path().to_str().unwrap(),
            make_minimal_prompts(),
        );
        let story = StoryConfig {
            num_users: 1,
            eval_batch_size: 1,
            duration_days: 1,
            ..StoryConfig::new("Empty", "X", "X")
        };
        let output = gen.generate_tenant(&story).unwrap();
        assert!(output.summary.contains("Failed"));
    }

    #[test]
    fn test_generate_eval_dataset_creates_files() {
        let dir = TempDir::new().unwrap();
        let base_path = dir.path().to_str().unwrap();

        // Create a minimal generation log
        let log = serde_json::json!([
            {"date": "2025-01-01", "type": "storyline", "events": ["Event A", "Event B"]},
            {"date": "2025-01-01", "type": "email", "id": "e1", "from": "user1", "subject": "Hi", "summary": "test email"},
            {"date": "2025-01-01", "type": "file", "path": "data/test.md", "created_by": "user1", "summary": "test file"}
        ]);
        fs::write(
            format!("{}/generation_log.json", base_path),
            serde_json::to_string_pretty(&log).unwrap(),
        )
        .unwrap();
        fs::write(
            format!("{}/tenant.yaml", base_path),
            "id: test\ndomain: test.com\nusers: []\n",
        )
        .unwrap();

        let prompts = make_minimal_prompts();
        let gen = DataGenerator::with_prompts(
            Box::new(PipelineMockProvider),
            base_path,
            prompts,
        );
        gen.generate_eval_dataset("test-tenant", base_path, 10, 5)
            .unwrap();

        // Check that at least one eval file was created
        let entries: Vec<_> = fs::read_dir(base_path)
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().to_string())
            .collect();
        let has_eval_log = entries.iter().any(|f| f.starts_with("eval_dataset_log_"));
        let has_eval_yaml = entries.iter().any(|f| f.starts_with("eval_dataset_") && f.ends_with(".yaml"));
        assert!(has_eval_log, "Expected eval_dataset_log_*.json");
        assert!(has_eval_yaml, "Expected eval_dataset_*.yaml");
    }

    #[test]
    fn test_parse_json_users_response() {
        let resp = r#"{"users": [{"id": "u1", "username": "u1"}]}"#;
        let v = parse_json(resp);
        let users = v.get("users").and_then(|v| v.as_array()).unwrap();
        assert_eq!(users[0].get("id").and_then(|v| v.as_str()), Some("u1"));
    }

    #[test]
    fn test_parse_json_daily_events() {
        let resp = r#"{"daily_events": ["Event A", "Event B"]}"#;
        let v = parse_json(resp);
        let events = v.get("daily_events").and_then(|v| v.as_array()).unwrap();
        assert_eq!(events.len(), 2);
    }

    #[test]
    fn test_format_template_preserves_json_example_braces() {
        let template = "Output: {{\"id\": \"{id}\"}}";
        let result = format_template(template, &[("id", "test123")]);
        assert_eq!(result, "Output: {\"id\": \"test123\"}");
    }
}
