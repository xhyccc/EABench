
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

def test_sandbox():
    config = MockTenantConfig()
    sandbox = LocalSandbox(config)
    sandbox.start()
    
    print(f"Sandbox root: {sandbox.root_dir}")
    
    # Check if data directory exists
    data_dir = os.path.join(sandbox.root_dir, "data")
    if os.path.exists(data_dir):
        print("SUCCESS: 'data' directory exists in sandbox.")
    else:
        print("FAILURE: 'data' directory MISSING in sandbox.")
        
    # Try to read a file using the path from files.yaml
    test_path = "data/memos/all-hands-scaling-email.txt"
    try:
        content = sandbox.read_file(test_path)
        print(f"SUCCESS: Successfully read '{test_path}'. Content length: {len(content)}")
    except Exception as e:
        print(f"FAILURE: Failed to read '{test_path}': {e}")
        
    sandbox.stop()

if __name__ == "__main__":
    test_sandbox()
