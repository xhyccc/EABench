use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

// ---------------------------------------------------------------------------
// User models
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct UserName {
    pub display_name: String,
    pub first_name: String,
    pub last_name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub nickname: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct UserProfile {
    pub email: String,
    pub name: UserName,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub manager_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub skip_manager_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub department: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub skills: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub location: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timezone: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct UserInfo {
    pub id: String,
    pub username: String,
    #[serde(default)]
    pub groups: Vec<String>,
    pub profile: UserProfile,
}

// ---------------------------------------------------------------------------
// File metadata
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct FileMetadata {
    pub path: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub created_by: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub created_time: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_modified_by: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_modified_time: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub snippet: Option<String>,
}

// ---------------------------------------------------------------------------
// Chat / GroupChat models
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ChatMessage {
    pub from_user: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub to_user: Option<String>,
    pub content: String,
    pub timestamp: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Chat {
    pub id: String,
    pub participants: Vec<String>,
    #[serde(default)]
    pub messages: Vec<ChatMessage>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct GroupChat {
    pub id: String,
    pub name: String,
    pub participants: Vec<String>,
    #[serde(default)]
    pub messages: Vec<ChatMessage>,
}

// ---------------------------------------------------------------------------
// Meeting model
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Meeting {
    pub id: String,
    pub title: String,
    pub organizer: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub invitees: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub attendees: Vec<String>,
    pub start_time: String,
    pub end_time: String,
    pub agenda: String,
    #[serde(default = "default_location")]
    pub location: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript: Option<String>,
}

fn default_location() -> String {
    "online".to_string()
}

// ---------------------------------------------------------------------------
// Email model
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Email {
    pub id: String,
    pub from_user: String,
    pub to_users: Vec<String>,
    #[serde(default)]
    pub cc_users: Vec<String>,
    #[serde(default)]
    pub bcc_users: Vec<String>,
    pub subject: String,
    pub body: String,
    pub timestamp: String,
}

// ---------------------------------------------------------------------------
// Channel model
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ChannelPost {
    pub id: String,
    pub author: String,
    pub content: String,
    pub timestamp: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Channel {
    pub id: String,
    pub name: String,
    pub participants: Vec<String>,
    #[serde(default)]
    pub posts: Vec<ChannelPost>,
}

// ---------------------------------------------------------------------------
// TenantConfig – top-level configuration object
// ---------------------------------------------------------------------------

/// Tenant configuration loaded from a `tenant.yaml` file.
///
/// Additional sub-configs (files, chats, emails, …) are loaded from the
/// `config/` sub-directory sitting next to the YAML file.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct TenantConfig {
    pub id: String,
    #[serde(default = "default_domain")]
    pub domain: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub users: Vec<UserInfo>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub files_metadata: Vec<FileMetadata>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub chats: Vec<Chat>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub group_chats: Vec<GroupChat>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub meetings: Vec<Meeting>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub emails: Vec<Email>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub channels: Vec<Channel>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub resource_limits: HashMap<String, String>,

    // Runtime paths (not in YAML, set after loading)
    #[serde(skip)]
    pub data_path: Option<PathBuf>,
    #[serde(skip)]
    pub root_path: Option<PathBuf>,
}

fn default_domain() -> String {
    "example.com".to_string()
}

impl TenantConfig {
    /// Load a [`TenantConfig`] from a `tenant.yaml` file.
    ///
    /// Sub-config files in `config/` (files.yaml, chats.yaml, emails.yaml,
    /// group_chats.yaml, meetings.yaml, channels.yaml) are loaded and merged
    /// into the returned config.  User IDs in emails are resolved to email
    /// addresses using the tenant's user list.
    pub fn from_yaml(path: &Path) -> Result<Self> {
        let raw = fs::read_to_string(path)
            .with_context(|| format!("reading {}", path.display()))?;
        let mut config: TenantConfig =
            serde_yaml::from_str(&raw).with_context(|| format!("parsing {}", path.display()))?;

        let base_dir = path.parent().unwrap_or(Path::new(".")).to_path_buf();
        config.root_path = Some(base_dir.clone());

        let config_dir = base_dir.join("config");
        let data_dir = base_dir.join("data");

        // Load sub-config files
        if config_dir.exists() {
            config.files_metadata =
                Self::load_list(&config_dir.join("files.yaml")).unwrap_or_default();
            config.chats = Self::load_list(&config_dir.join("chats.yaml")).unwrap_or_default();
            config.group_chats =
                Self::load_list(&config_dir.join("group_chats.yaml")).unwrap_or_default();
            config.meetings =
                Self::load_list(&config_dir.join("meetings.yaml")).unwrap_or_default();
            config.emails =
                Self::load_list(&config_dir.join("emails.yaml")).unwrap_or_default();
            config.channels =
                Self::load_list(&config_dir.join("channels.yaml")).unwrap_or_default();
        }

        // Build user-id → email map and resolve IDs in Email objects
        let user_email_map: HashMap<String, String> = config
            .users
            .iter()
            .map(|u| {
                let email = if u.profile.email.is_empty() {
                    format!("{}@{}", u.username, config.domain)
                } else {
                    u.profile.email.clone()
                };
                (u.id.clone(), email)
            })
            .collect();

        for email in &mut config.emails {
            if let Some(resolved) = user_email_map.get(&email.from_user) {
                email.from_user = resolved.clone();
            }
            email.to_users = email
                .to_users
                .iter()
                .map(|u| user_email_map.get(u).cloned().unwrap_or_else(|| u.clone()))
                .collect();
            email.cc_users = email
                .cc_users
                .iter()
                .map(|u| user_email_map.get(u).cloned().unwrap_or_else(|| u.clone()))
                .collect();
            email.bcc_users = email
                .bcc_users
                .iter()
                .map(|u| user_email_map.get(u).cloned().unwrap_or_else(|| u.clone()))
                .collect();
        }

        if data_dir.exists() {
            config.data_path = Some(data_dir);
        }

        Ok(config)
    }

    fn load_list<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<Vec<T>> {
        if !path.exists() {
            return Ok(vec![]);
        }
        let raw = fs::read_to_string(path)
            .with_context(|| format!("reading {}", path.display()))?;
        let items: Option<Vec<T>> = serde_yaml::from_str(&raw)
            .with_context(|| format!("parsing {}", path.display()))?;
        Ok(items.unwrap_or_default())
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

    fn write_yaml(dir: &TempDir, name: &str, content: &str) -> PathBuf {
        let path = dir.path().join(name);
        let mut f = fs::File::create(&path).unwrap();
        write!(f, "{}", content).unwrap();
        path
    }

    fn make_tenant_yaml(dir: &TempDir) -> PathBuf {
        let yaml = r#"
id: test-tenant
domain: example.com
users:
  - id: user1
    username: alice
    groups: [admin]
    profile:
      email: alice@example.com
      name:
        display_name: Alice Smith
        first_name: Alice
        last_name: Smith
      department: Engineering
      skills: [Rust, Python]
      title: Engineer
"#;
        fs::create_dir_all(dir.path().join("config")).unwrap();
        fs::create_dir_all(dir.path().join("data")).unwrap();
        write_yaml(dir, "tenant.yaml", yaml)
    }

    #[test]
    fn test_from_yaml_loads_id_and_domain() {
        let dir = TempDir::new().unwrap();
        let path = make_tenant_yaml(&dir);
        let cfg = TenantConfig::from_yaml(&path).unwrap();
        assert_eq!(cfg.id, "test-tenant");
        assert_eq!(cfg.domain, "example.com");
    }

    #[test]
    fn test_from_yaml_loads_users() {
        let dir = TempDir::new().unwrap();
        let path = make_tenant_yaml(&dir);
        let cfg = TenantConfig::from_yaml(&path).unwrap();
        assert_eq!(cfg.users.len(), 1);
        assert_eq!(cfg.users[0].username, "alice");
        assert_eq!(cfg.users[0].profile.email, "alice@example.com");
    }

    #[test]
    fn test_from_yaml_sets_root_path() {
        let dir = TempDir::new().unwrap();
        let path = make_tenant_yaml(&dir);
        let cfg = TenantConfig::from_yaml(&path).unwrap();
        assert!(cfg.root_path.is_some());
        assert_eq!(cfg.root_path.unwrap(), dir.path());
    }

    #[test]
    fn test_from_yaml_sets_data_path() {
        let dir = TempDir::new().unwrap();
        let path = make_tenant_yaml(&dir);
        let cfg = TenantConfig::from_yaml(&path).unwrap();
        assert!(cfg.data_path.is_some());
    }

    #[test]
    fn test_from_yaml_loads_files_config() {
        let dir = TempDir::new().unwrap();
        let path = make_tenant_yaml(&dir);
        let files_yaml = r#"
- path: data/docs/readme.txt
  snippet: A readme
  created_by: user1
"#;
        write_yaml(&dir, "config/files.yaml", files_yaml);
        let cfg = TenantConfig::from_yaml(&path).unwrap();
        assert_eq!(cfg.files_metadata.len(), 1);
        assert_eq!(cfg.files_metadata[0].snippet.as_deref(), Some("A readme"));
    }

    #[test]
    fn test_from_yaml_resolves_email_user_ids() {
        let dir = TempDir::new().unwrap();
        let path = make_tenant_yaml(&dir);
        let emails_yaml = r#"
- id: e1
  from_user: user1
  to_users: [user1]
  cc_users: []
  bcc_users: []
  subject: Test
  body: Hello
  timestamp: "2025-01-01T09:00:00"
"#;
        write_yaml(&dir, "config/emails.yaml", emails_yaml);
        let cfg = TenantConfig::from_yaml(&path).unwrap();
        assert_eq!(cfg.emails[0].from_user, "alice@example.com");
        assert_eq!(cfg.emails[0].to_users, vec!["alice@example.com"]);
    }

    #[test]
    fn test_from_yaml_missing_subconfigs_returns_empty() {
        let dir = TempDir::new().unwrap();
        let path = make_tenant_yaml(&dir);
        let cfg = TenantConfig::from_yaml(&path).unwrap();
        assert!(cfg.emails.is_empty());
        assert!(cfg.chats.is_empty());
        assert!(cfg.meetings.is_empty());
    }

    #[test]
    fn test_default_domain() {
        let yaml = "id: t1\n";
        let dir = TempDir::new().unwrap();
        let path = write_yaml(&dir, "tenant.yaml", yaml);
        let cfg = TenantConfig::from_yaml(&path).unwrap();
        assert_eq!(cfg.domain, "example.com");
    }
}
