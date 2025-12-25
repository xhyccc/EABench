
import os
import shutil
import tempfile
from src.sandbox.local_sandbox import LocalSandbox
from src.config.tenant_config import TenantConfig

# Mock TenantConfig
class MockTenantConfig:
    def __init__(self):
        self.id = "test_tenant"
        self.data_path = "examples/tenants/technova-20251224/data"

def test_list_files():
    config = MockTenantConfig()
    sandbox = LocalSandbox(config)
    sandbox.start()
    
    print("--- Root Listing ---")
    root_files = sandbox.list_files(".")
    print(root_files)
    
    if "data" in root_files:
        print("\n--- Data Listing ---")
        data_files = sandbox.list_files("data")
        print(data_files)
    
    sandbox.stop()

if __name__ == "__main__":
    test_list_files()
