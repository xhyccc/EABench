use crate::config::tenant_config::TenantConfig;
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// SearchResult
// ---------------------------------------------------------------------------

/// A single ranked search result.
#[derive(Debug, Clone, PartialEq)]
pub struct SearchResult {
    /// Simple relevance score in [0.0, 1.0] based on keyword overlap.
    pub score: f64,
    /// Type of the matched item (e.g. "file", "email", "chat", …)
    pub kind: String,
    /// Display title / identifier.
    pub title: String,
    /// Snippet of the matched content.
    pub snippet: String,
    /// Free-form metadata (item id, path, author, …)
    pub metadata: HashMap<String, String>,
}

// ---------------------------------------------------------------------------
// SearchEngine
// ---------------------------------------------------------------------------

/// A lightweight, text-based search engine that operates over a
/// [`TenantConfig`].
///
/// This implementation uses simple keyword-overlap scoring so that it works
/// without any external dependencies or LLM calls.  It mirrors the overall
/// API shape of the Python `SearchEngine` while remaining dependency-free.
pub struct SearchEngine {
    tenant: TenantConfig,
    current_user_id: Option<String>,
    current_user_emails: Vec<String>,
}

impl SearchEngine {
    pub fn new(tenant: TenantConfig) -> Self {
        SearchEngine {
            tenant,
            current_user_id: None,
            current_user_emails: Vec::new(),
        }
    }

    /// Set the user context used for access-control filtering.
    pub fn set_user_context(&mut self, user_id: &str) {
        self.current_user_id = Some(user_id.to_string());
        self.current_user_emails = Vec::new();

        if let Some(user) = self.tenant.users.iter().find(|u| u.id == user_id) {
            if !user.profile.email.is_empty() {
                self.current_user_emails.push(user.profile.email.clone());
            }
            let constructed = format!("{}@{}", user.username, self.tenant.domain);
            if !self.current_user_emails.contains(&constructed) {
                self.current_user_emails.push(constructed);
            }
        }
    }

    // -----------------------------------------------------------------------
    // Public search methods
    // -----------------------------------------------------------------------

    /// Search file snippets and file-content index.
    pub fn search_files(&self, query: &str, top_k: usize) -> Vec<SearchResult> {
        let mut results: Vec<SearchResult> = self
            .tenant
            .files_metadata
            .iter()
            .filter_map(|fm| {
                let text = format!(
                    "{} {} {}",
                    fm.path,
                    fm.snippet.as_deref().unwrap_or(""),
                    fm.created_by.as_deref().unwrap_or("")
                );
                let score = keyword_score(query, &text);
                if score > 0.0 {
                    let mut meta = HashMap::new();
                    meta.insert("path".to_string(), fm.path.clone());
                    if let Some(ref cb) = fm.created_by {
                        meta.insert("created_by".to_string(), cb.clone());
                    }
                    Some(SearchResult {
                        score,
                        kind: "file".to_string(),
                        title: fm.path.clone(),
                        snippet: fm.snippet.clone().unwrap_or_default(),
                        metadata: meta,
                    })
                } else {
                    None
                }
            })
            .collect();

        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
        results.truncate(top_k);
        results
    }

    /// Search emails.
    pub fn search_emails(&self, query: &str, top_k: usize) -> Vec<SearchResult> {
        let mut results: Vec<SearchResult> = self
            .tenant
            .emails
            .iter()
            .filter(|e| self.email_visible_to_user(e))
            .filter_map(|e| {
                let text = format!("{} {} {}", e.subject, e.body, e.from_user);
                let score = keyword_score(query, &text);
                if score > 0.0 {
                    let mut meta = HashMap::new();
                    meta.insert("id".to_string(), e.id.clone());
                    meta.insert("from".to_string(), e.from_user.clone());
                    meta.insert("subject".to_string(), e.subject.clone());
                    Some(SearchResult {
                        score,
                        kind: "email".to_string(),
                        title: e.subject.clone(),
                        snippet: e.body.chars().take(200).collect(),
                        metadata: meta,
                    })
                } else {
                    None
                }
            })
            .collect();

        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
        results.truncate(top_k);
        results
    }

    /// Search chats (direct messages).
    pub fn search_chats(&self, query: &str, top_k: usize) -> Vec<SearchResult> {
        let mut results: Vec<SearchResult> = self
            .tenant
            .chats
            .iter()
            .filter_map(|chat| {
                let text = chat
                    .messages
                    .iter()
                    .map(|m| format!("{}: {}", m.from_user, m.content))
                    .collect::<Vec<_>>()
                    .join("\n");
                let score = keyword_score(query, &text);
                if score > 0.0 {
                    let mut meta = HashMap::new();
                    meta.insert("id".to_string(), chat.id.clone());
                    Some(SearchResult {
                        score,
                        kind: "chat".to_string(),
                        title: format!("Chat {}", chat.id),
                        snippet: text.chars().take(200).collect(),
                        metadata: meta,
                    })
                } else {
                    None
                }
            })
            .collect();

        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
        results.truncate(top_k);
        results
    }

    /// Search meetings.
    pub fn search_meetings(&self, query: &str, top_k: usize) -> Vec<SearchResult> {
        let mut results: Vec<SearchResult> = self
            .tenant
            .meetings
            .iter()
            .filter_map(|m| {
                let text = format!(
                    "{} {} {}",
                    m.title,
                    m.agenda,
                    m.transcript.as_deref().unwrap_or("")
                );
                let score = keyword_score(query, &text);
                if score > 0.0 {
                    let mut meta = HashMap::new();
                    meta.insert("id".to_string(), m.id.clone());
                    meta.insert("organizer".to_string(), m.organizer.clone());
                    Some(SearchResult {
                        score,
                        kind: "meeting".to_string(),
                        title: m.title.clone(),
                        snippet: m.agenda.chars().take(200).collect(),
                        metadata: meta,
                    })
                } else {
                    None
                }
            })
            .collect();

        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
        results.truncate(top_k);
        results
    }

    /// Search users / people.
    pub fn search_people(&self, query: &str, top_k: usize) -> Vec<SearchResult> {
        let mut results: Vec<SearchResult> = self
            .tenant
            .users
            .iter()
            .filter_map(|u| {
                let text = format!(
                    "{} {} {} {} {}",
                    u.profile.name.display_name,
                    u.username,
                    u.profile.email,
                    u.profile.title.as_deref().unwrap_or(""),
                    u.profile.department.as_deref().unwrap_or("")
                );
                let score = keyword_score(query, &text);
                if score > 0.0 {
                    let mut meta = HashMap::new();
                    meta.insert("id".to_string(), u.id.clone());
                    meta.insert("email".to_string(), u.profile.email.clone());
                    Some(SearchResult {
                        score,
                        kind: "user".to_string(),
                        title: u.profile.name.display_name.clone(),
                        snippet: format!(
                            "{} – {}",
                            u.profile.title.as_deref().unwrap_or(""),
                            u.profile.department.as_deref().unwrap_or("")
                        ),
                        metadata: meta,
                    })
                } else {
                    None
                }
            })
            .collect();

        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
        results.truncate(top_k);
        results
    }

    // -----------------------------------------------------------------------
    // Private helpers
    // -----------------------------------------------------------------------

    fn email_visible_to_user(&self, email: &crate::config::tenant_config::Email) -> bool {
        if self.current_user_id.is_some() {
            let user_emails = &self.current_user_emails;
            if user_emails.is_empty() {
                return false;
            }
            // User can see the email if they are sender, recipient, cc, or bcc
            return user_emails.iter().any(|ue| {
                email.from_user == *ue
                    || email.to_users.contains(ue)
                    || email.cc_users.contains(ue)
                    || email.bcc_users.contains(ue)
            });
        }
        true // no user context → show all
    }
}

// ---------------------------------------------------------------------------
// Keyword scoring
// ---------------------------------------------------------------------------

/// Simple keyword-overlap score: (matching tokens) / (query tokens).
///
/// Case-insensitive.  Returns 0.0 when *query* is empty.
fn keyword_score(query: &str, text: &str) -> f64 {
    let query_tokens: Vec<String> = tokenize(query);
    if query_tokens.is_empty() {
        return 0.0;
    }
    let text_lower = text.to_lowercase();
    let matches = query_tokens
        .iter()
        .filter(|t| text_lower.contains(t.as_str()))
        .count();
    matches as f64 / query_tokens.len() as f64
}

fn tokenize(s: &str) -> Vec<String> {
    s.split_whitespace()
        .map(|t| t.to_lowercase())
        .filter(|t| t.len() > 1)
        .collect()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::tenant_config::*;

    fn make_tenant() -> TenantConfig {
        TenantConfig {
            id: "test".to_string(),
            domain: "example.com".to_string(),
            users: vec![
                UserInfo {
                    id: "u1".to_string(),
                    username: "alice".to_string(),
                    groups: vec![],
                    profile: UserProfile {
                        email: "alice@example.com".to_string(),
                        name: UserName {
                            display_name: "Alice Smith".to_string(),
                            first_name: "Alice".to_string(),
                            last_name: "Smith".to_string(),
                            nickname: None,
                        },
                        manager_id: None,
                        skip_manager_id: None,
                        department: Some("Engineering".to_string()),
                        skills: vec!["Rust".to_string()],
                        title: Some("Engineer".to_string()),
                        location: None,
                        timezone: None,
                    },
                },
                UserInfo {
                    id: "u2".to_string(),
                    username: "bob".to_string(),
                    groups: vec![],
                    profile: UserProfile {
                        email: "bob@example.com".to_string(),
                        name: UserName {
                            display_name: "Bob Jones".to_string(),
                            first_name: "Bob".to_string(),
                            last_name: "Jones".to_string(),
                            nickname: None,
                        },
                        manager_id: None,
                        skip_manager_id: None,
                        department: Some("Marketing".to_string()),
                        skills: vec![],
                        title: Some("Manager".to_string()),
                        location: None,
                        timezone: None,
                    },
                },
            ],
            files_metadata: vec![
                FileMetadata {
                    path: "data/docs/report.txt".to_string(),
                    created_by: Some("u1".to_string()),
                    created_time: None,
                    last_modified_by: None,
                    last_modified_time: None,
                    snippet: Some("Quarterly earnings report".to_string()),
                },
                FileMetadata {
                    path: "data/notes/meeting.txt".to_string(),
                    created_by: None,
                    created_time: None,
                    last_modified_by: None,
                    last_modified_time: None,
                    snippet: Some("Team meeting notes".to_string()),
                },
            ],
            emails: vec![Email {
                id: "e1".to_string(),
                from_user: "alice@example.com".to_string(),
                to_users: vec!["bob@example.com".to_string()],
                cc_users: vec![],
                bcc_users: vec![],
                subject: "Budget Review".to_string(),
                body: "Please review the Q4 budget.".to_string(),
                timestamp: "2025-01-01T10:00:00".to_string(),
            }],
            chats: vec![Chat {
                id: "c1".to_string(),
                participants: vec!["u1".to_string(), "u2".to_string()],
                messages: vec![
                    ChatMessage {
                        from_user: "u1".to_string(),
                        to_user: Some("u2".to_string()),
                        content: "Hey Bob!".to_string(),
                        timestamp: "2025-01-01T09:00:00".to_string(),
                    },
                    ChatMessage {
                        from_user: "u2".to_string(),
                        to_user: Some("u1".to_string()),
                        content: "Hi Alice!".to_string(),
                        timestamp: "2025-01-01T09:01:00".to_string(),
                    },
                ],
            }],
            meetings: vec![Meeting {
                id: "m1".to_string(),
                title: "Sprint Planning".to_string(),
                organizer: "u1".to_string(),
                invitees: vec![],
                attendees: vec![],
                start_time: "2025-01-02T09:00:00".to_string(),
                end_time: "2025-01-02T10:00:00".to_string(),
                agenda: "Plan the sprint".to_string(),
                location: "online".to_string(),
                transcript: Some("Alice: Let's plan...".to_string()),
            }],
            group_chats: vec![],
            channels: vec![],
            resource_limits: HashMap::new(),
            data_path: None,
            root_path: None,
        }
    }

    // --- keyword_score tests -----------------------------------------------

    #[test]
    fn test_keyword_score_full_match() {
        let score = keyword_score("hello world", "hello world");
        assert!((score - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_keyword_score_partial_match() {
        let score = keyword_score("hello world", "only hello here");
        assert!((score - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_keyword_score_no_match() {
        let score = keyword_score("xyz abc", "no overlapping words");
        assert_eq!(score, 0.0);
    }

    #[test]
    fn test_keyword_score_case_insensitive() {
        let score = keyword_score("Hello World", "hello world");
        assert!((score - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_keyword_score_empty_query() {
        assert_eq!(keyword_score("", "some text"), 0.0);
    }

    // --- search_files tests ------------------------------------------------

    #[test]
    fn test_search_files_returns_matching_results() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_files("report", 5);
        assert!(!results.is_empty());
        assert_eq!(results[0].kind, "file");
    }

    #[test]
    fn test_search_files_respects_top_k() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_files("data", 1);
        assert!(results.len() <= 1);
    }

    #[test]
    fn test_search_files_no_match_returns_empty() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_files("zzz_nomatch_zzz", 5);
        assert!(results.is_empty());
    }

    #[test]
    fn test_search_files_result_contains_metadata() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_files("report", 5);
        assert!(!results.is_empty());
        assert!(results[0].metadata.contains_key("path"));
    }

    // --- search_emails tests -----------------------------------------------

    #[test]
    fn test_search_emails_no_user_context_returns_all() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_emails("budget", 5);
        assert!(!results.is_empty());
    }

    #[test]
    fn test_search_emails_with_user_context_returns_visible() {
        let mut engine = SearchEngine::new(make_tenant());
        engine.set_user_context("u1");
        let results = engine.search_emails("budget", 5);
        assert!(!results.is_empty());
    }

    #[test]
    fn test_search_emails_returns_email_kind() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_emails("budget", 5);
        assert!(!results.is_empty());
        assert_eq!(results[0].kind, "email");
    }

    // --- search_chats tests ------------------------------------------------

    #[test]
    fn test_search_chats_returns_matching_results() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_chats("Alice", 5);
        assert!(!results.is_empty());
    }

    #[test]
    fn test_search_chats_no_match_returns_empty() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_chats("zzznosuchthing", 5);
        assert!(results.is_empty());
    }

    // --- search_meetings tests ---------------------------------------------

    #[test]
    fn test_search_meetings_returns_matching_results() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_meetings("sprint planning", 5);
        assert!(!results.is_empty());
        assert_eq!(results[0].kind, "meeting");
    }

    #[test]
    fn test_search_meetings_no_match_returns_empty() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_meetings("zzznosuchthing", 5);
        assert!(results.is_empty());
    }

    // --- search_people tests -----------------------------------------------

    #[test]
    fn test_search_people_returns_matching_results() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_people("Alice Smith", 5);
        assert!(!results.is_empty());
        assert_eq!(results[0].kind, "user");
    }

    #[test]
    fn test_search_people_no_match_returns_empty() {
        let engine = SearchEngine::new(make_tenant());
        let results = engine.search_people("zzznosuchthing", 5);
        assert!(results.is_empty());
    }

    // --- set_user_context tests --------------------------------------------

    #[test]
    fn test_set_user_context_populates_emails() {
        let mut engine = SearchEngine::new(make_tenant());
        engine.set_user_context("u1");
        assert_eq!(engine.current_user_id.as_deref(), Some("u1"));
        assert!(engine.current_user_emails.contains(&"alice@example.com".to_string()));
    }

    #[test]
    fn test_set_user_context_unknown_user_gives_empty_emails() {
        let mut engine = SearchEngine::new(make_tenant());
        engine.set_user_context("unknown");
        assert!(engine.current_user_emails.is_empty());
    }
}
