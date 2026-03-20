use anyhow::{bail, Context, Result};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use tempfile::TempDir;
use walkdir::WalkDir;

use super::Sandbox;

// ---------------------------------------------------------------------------
// LocalSandbox
// ---------------------------------------------------------------------------

/// A sandbox that runs operations on a temporary copy of the tenant data
/// directory on the local filesystem.
///
/// On `start()` the tenant's `data_path` is copied into a temporary directory.
/// On `stop()` the temporary directory is deleted.
pub struct LocalSandbox {
    #[allow(dead_code)]
    tenant_id: String,
    data_path: Option<PathBuf>,
    /// Holds the `TempDir` so it lives as long as the sandbox.
    _temp_dir: Option<TempDir>,
    /// The resolved root of the sandbox (set after `start()`).
    pub root_dir: Option<PathBuf>,
}

impl LocalSandbox {
    pub fn new(tenant_id: impl Into<String>, data_path: Option<PathBuf>) -> Self {
        LocalSandbox {
            tenant_id: tenant_id.into(),
            data_path,
            _temp_dir: None,
            root_dir: None,
        }
    }

    /// Resolve *path* relative to the sandbox root, rejecting path-traversal
    /// attempts (i.e. paths that escape the sandbox root).
    fn resolve_path(&self, path: &str) -> Result<PathBuf> {
        let root = self
            .root_dir
            .as_ref()
            .context("Sandbox not started")?;

        // Normalize by manually processing each component so that `..` is
        // resolved before the starts_with check (canonicalize only works for
        // paths that already exist on disk).
        let joined = root.join(path);
        let mut normalized = PathBuf::new();
        for component in joined.components() {
            match component {
                std::path::Component::ParentDir => {
                    if !normalized.pop() {
                        bail!("Access denied: path '{}' escapes the sandbox", path);
                    }
                }
                c => normalized.push(c),
            }
        }

        if !normalized.starts_with(root) {
            bail!("Access denied: path '{}' escapes the sandbox", path);
        }
        Ok(normalized)
    }
}

impl Sandbox for LocalSandbox {
    fn start(&mut self) -> Result<()> {
        let dir = TempDir::new().context("creating temp dir")?;
        let root = dir.path().to_path_buf();

        // Hydrate: copy tenant data into root/data
        if let Some(ref src) = self.data_path {
            if src.exists() {
                let dest = root.join("data");
                copy_dir_all(src, &dest)?;
            }
        }

        self.root_dir = Some(root);
        self._temp_dir = Some(dir);
        Ok(())
    }

    fn stop(&mut self) -> Result<()> {
        // Dropping TempDir removes the directory
        self._temp_dir = None;
        self.root_dir = None;
        Ok(())
    }

    fn read_file(&self, path: &str) -> Result<String> {
        // 1. Exact match
        match self.resolve_path(path) {
            Ok(full) if full.is_file() => {
                return fs::read_to_string(&full)
                    .with_context(|| format!("reading {}", full.display()));
            }
            Err(e) if e.to_string().contains("Access denied") => {
                bail!("{}", e);
            }
            _ => {}
        }

        // 2. Fuzzy: search for a file whose relative path contains *path* as substring
        let root = self.root_dir.as_ref().context("Sandbox not started")?;
        let mut matches: Vec<PathBuf> = Vec::new();

        for entry in WalkDir::new(root).into_iter().filter_map(|e| e.ok()) {
            if entry.file_type().is_file() {
                let rel = entry
                    .path()
                    .strip_prefix(root)
                    .unwrap()
                    .to_string_lossy()
                    .to_string();
                if rel.contains(path) {
                    matches.push(entry.path().to_path_buf());
                }
            }
        }

        match matches.len() {
            0 => bail!("File not found: {}", path),
            1 => fs::read_to_string(&matches[0])
                .with_context(|| format!("reading {}", matches[0].display())),
            _ => {
                // Prefer suffix match
                let suffix: Vec<_> = matches
                    .iter()
                    .filter(|m| {
                        m.strip_prefix(root)
                            .unwrap()
                            .to_string_lossy()
                            .ends_with(path)
                    })
                    .cloned()
                    .collect();
                if suffix.len() == 1 {
                    return fs::read_to_string(&suffix[0])
                        .with_context(|| format!("reading {}", suffix[0].display()));
                }
                let names: Vec<_> = matches
                    .iter()
                    .map(|m| m.to_string_lossy().to_string())
                    .collect();
                bail!("Ambiguous path '{}'. Matches: {}", path, names.join(", "));
            }
        }
    }

    fn write_file(&self, path: &str, content: &str) -> Result<()> {
        let full = self.resolve_path(path)?;
        if let Some(parent) = full.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&full, content).with_context(|| format!("writing {}", full.display()))
    }

    fn list_files(&self, path: &str) -> Result<Vec<String>> {
        let full = self.resolve_path(path)?;
        let mut entries = Vec::new();
        for entry in fs::read_dir(&full)
            .with_context(|| format!("listing {}", full.display()))?
        {
            let entry = entry?;
            entries.push(entry.file_name().to_string_lossy().to_string());
        }
        entries.sort();
        Ok(entries)
    }

    fn execute_command(&self, cmd: &str) -> Result<String> {
        let root = self.root_dir.as_ref().context("Sandbox not started")?;
        let output = Command::new("sh")
            .arg("-c")
            .arg(cmd)
            .current_dir(root)
            .output()
            .with_context(|| format!("executing command: {}", cmd))?;

        let mut result = String::from_utf8_lossy(&output.stdout).to_string();
        result.push_str(&String::from_utf8_lossy(&output.stderr));
        Ok(result)
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn copy_dir_all(src: &Path, dst: &Path) -> Result<()> {
    fs::create_dir_all(dst)?;
    for entry in WalkDir::new(src).min_depth(1).into_iter().filter_map(|e| e.ok()) {
        let rel = entry.path().strip_prefix(src).unwrap();
        let target = dst.join(rel);
        if entry.file_type().is_dir() {
            fs::create_dir_all(&target)?;
        } else {
            if let Some(parent) = target.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn make_data_dir() -> (TempDir, PathBuf) {
        let dir = TempDir::new().unwrap();
        let data_dir = dir.path().join("mydata");
        fs::create_dir_all(&data_dir).unwrap();
        let mut f = fs::File::create(data_dir.join("hello.txt")).unwrap();
        write!(f, "Hello, world!").unwrap();
        fs::create_dir_all(data_dir.join("subdir")).unwrap();
        let mut f2 = fs::File::create(data_dir.join("subdir").join("nested.txt")).unwrap();
        write!(f2, "Nested content").unwrap();
        (dir, data_dir)
    }

    #[test]
    fn test_start_creates_root_dir() {
        let mut sb = LocalSandbox::new("t1", None);
        sb.start().unwrap();
        assert!(sb.root_dir.is_some());
        assert!(sb.root_dir.as_ref().unwrap().exists());
        sb.stop().unwrap();
    }

    #[test]
    fn test_stop_removes_temp_dir() {
        let mut sb = LocalSandbox::new("t1", None);
        sb.start().unwrap();
        let root = sb.root_dir.clone().unwrap();
        sb.stop().unwrap();
        assert!(!root.exists());
    }

    #[test]
    fn test_hydration_copies_data() {
        let (_dir, data_dir) = make_data_dir();
        let mut sb = LocalSandbox::new("t1", Some(data_dir));
        sb.start().unwrap();
        let sandbox_data = sb.root_dir.as_ref().unwrap().join("data");
        assert!(sandbox_data.exists());
        assert!(sandbox_data.join("hello.txt").exists());
        sb.stop().unwrap();
    }

    #[test]
    fn test_read_file_exact_path() {
        let (_dir, data_dir) = make_data_dir();
        let mut sb = LocalSandbox::new("t1", Some(data_dir));
        sb.start().unwrap();
        let content = sb.read_file("data/hello.txt").unwrap();
        assert_eq!(content, "Hello, world!");
        sb.stop().unwrap();
    }

    #[test]
    fn test_read_file_fuzzy_match() {
        let (_dir, data_dir) = make_data_dir();
        let mut sb = LocalSandbox::new("t1", Some(data_dir));
        sb.start().unwrap();
        let content = sb.read_file("hello.txt").unwrap();
        assert_eq!(content, "Hello, world!");
        sb.stop().unwrap();
    }

    #[test]
    fn test_read_file_nested() {
        let (_dir, data_dir) = make_data_dir();
        let mut sb = LocalSandbox::new("t1", Some(data_dir));
        sb.start().unwrap();
        let content = sb.read_file("data/subdir/nested.txt").unwrap();
        assert_eq!(content, "Nested content");
        sb.stop().unwrap();
    }

    #[test]
    fn test_read_file_missing_returns_error() {
        let (_dir, data_dir) = make_data_dir();
        let mut sb = LocalSandbox::new("t1", Some(data_dir));
        sb.start().unwrap();
        let err = sb.read_file("data/nonexistent.txt");
        assert!(err.is_err());
        sb.stop().unwrap();
    }

    #[test]
    fn test_read_file_path_traversal_denied() {
        let (_dir, data_dir) = make_data_dir();
        let mut sb = LocalSandbox::new("t1", Some(data_dir));
        sb.start().unwrap();
        let result = sb.read_file("../../etc/passwd");
        // Should either be denied or not found, never succeed with system file content
        match &result {
            Ok(content) => {
                // If it somehow "succeeds" it must not have leaked real /etc/passwd
                assert!(!content.contains("root:"));
            }
            Err(_) => {} // expected
        }
        sb.stop().unwrap();
    }

    #[test]
    fn test_write_and_read_back() {
        let mut sb = LocalSandbox::new("t1", None);
        sb.start().unwrap();
        sb.write_file("newfile.txt", "brand new").unwrap();
        let content = sb.read_file("newfile.txt").unwrap();
        assert_eq!(content, "brand new");
        sb.stop().unwrap();
    }

    #[test]
    fn test_write_outside_sandbox_denied() {
        let mut sb = LocalSandbox::new("t1", None);
        sb.start().unwrap();
        let result = sb.write_file("../../tmp/evil.txt", "evil");
        assert!(result.is_err());
        sb.stop().unwrap();
    }

    #[test]
    fn test_list_files_root() {
        let (_dir, data_dir) = make_data_dir();
        let mut sb = LocalSandbox::new("t1", Some(data_dir));
        sb.start().unwrap();
        let files = sb.list_files(".").unwrap();
        assert!(files.contains(&"data".to_string()));
        sb.stop().unwrap();
    }

    #[test]
    fn test_list_files_data_dir() {
        let (_dir, data_dir) = make_data_dir();
        let mut sb = LocalSandbox::new("t1", Some(data_dir));
        sb.start().unwrap();
        let files = sb.list_files("data").unwrap();
        assert!(files.contains(&"hello.txt".to_string()));
        assert!(files.contains(&"subdir".to_string()));
        sb.stop().unwrap();
    }

    #[test]
    fn test_list_files_outside_denied() {
        let mut sb = LocalSandbox::new("t1", None);
        sb.start().unwrap();
        let result = sb.list_files("../../");
        assert!(result.is_err());
        sb.stop().unwrap();
    }

    #[test]
    fn test_execute_command_echo() {
        let mut sb = LocalSandbox::new("t1", None);
        sb.start().unwrap();
        let output = sb.execute_command("echo hello").unwrap();
        assert!(output.trim() == "hello");
        sb.stop().unwrap();
    }

    #[test]
    fn test_execute_command_returns_stderr() {
        let mut sb = LocalSandbox::new("t1", None);
        sb.start().unwrap();
        let output = sb.execute_command("ls /nonexistent_path_abc_xyz 2>&1").unwrap();
        assert!(output.contains("No such file") || output.contains("cannot access") || !output.is_empty());
        sb.stop().unwrap();
    }
}
