from abc import ABC, abstractmethod
from ..config.tenant_config import TenantConfig

class SandboxInterface(ABC):
    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def execute_command(self, cmd: str) -> str:
        pass
    
    @abstractmethod
    def read_file(self, path: str) -> str:
        pass
    
    @abstractmethod
    def write_file(self, path: str, content: str):
        pass
    
    @abstractmethod
    def list_files(self, path: str) -> list[str]:
        pass
