pub mod local_sandbox;

pub use local_sandbox::LocalSandbox;

use anyhow::Result;

/// Common interface implemented by all sandbox backends.
pub trait Sandbox {
    fn start(&mut self) -> Result<()>;
    fn stop(&mut self) -> Result<()>;
    fn read_file(&self, path: &str) -> Result<String>;
    fn write_file(&self, path: &str, content: &str) -> Result<()>;
    fn list_files(&self, path: &str) -> Result<Vec<String>>;
    fn execute_command(&self, cmd: &str) -> Result<String>;
}
