import os
import shutil
import tempfile
import subprocess
from .base import SandboxInterface
from ..config.tenant_config import TenantConfig

class LocalSandbox(SandboxInterface):
    def __init__(self, tenant_config: TenantConfig):
        self.tenant = tenant_config
        self.root_dir = None

    def start(self):
        self.root_dir = tempfile.mkdtemp(prefix=f"sandbox_{self.tenant.id}_")
        self._hydrate()

    def _hydrate(self):
        if not self.tenant.data_path or not os.path.exists(self.tenant.data_path):
            return

        # Copy all files from data_path to root_dir
        # We use shutil.copytree with dirs_exist_ok=True to merge into the temp dir
        shutil.copytree(self.tenant.data_path, self.root_dir, dirs_exist_ok=True)

    def stop(self):
        if self.root_dir and os.path.exists(self.root_dir):
            shutil.rmtree(self.root_dir)

    def _resolve_path(self, path: str) -> str:
        # Basic security check to prevent escaping sandbox
        full_path = os.path.abspath(os.path.join(self.root_dir, path))
        if not full_path.startswith(self.root_dir):
            raise ValueError("Access denied: Path outside sandbox")
        return full_path

    def execute_command(self, cmd: str) -> str:
        try:
            result = subprocess.run(
                cmd, 
                shell=True, 
                cwd=self.root_dir, 
                capture_output=True, 
                text=True,
                timeout=10
            )
            return result.stdout + result.stderr
        except Exception as e:
            return str(e)

    def read_file(self, path: str) -> str:
        full_path = self._resolve_path(path)
        with open(full_path, "r") as f:
            return f.read()

    def write_file(self, path: str, content: str):
        full_path = self._resolve_path(path)
        with open(full_path, "w") as f:
            f.write(content)

    def list_files(self, path: str) -> list[str]:
        full_path = self._resolve_path(path)
        return os.listdir(full_path)
