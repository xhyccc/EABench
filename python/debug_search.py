import asyncio
import os
from dotenv import load_dotenv
from src.config.agent_config import AgentConfig, ProviderType
from src.config.tenant_config import TenantConfig
from src.core.embedding_provider import LocalEmbeddingProvider, MockEmbeddingProvider
from src.core.search_engine import SearchEngine
from src.sandbox.local_sandbox import LocalSandbox

class MockQueryAnalyzer:
    async def analyze(self, query, domain, tool_name=None):
        return {"strategy": "semantic", "refined_query": query, "sender_name": None}

async def debug_search():
    # Load configs
    tenant_config = TenantConfig.from_yaml("examples/tenants/test-tenant-1/tenant.yaml")
    
    # Use Local Embedding
    embedding_provider = LocalEmbeddingProvider()
    
    sandbox = LocalSandbox(tenant_config)
    
    # Search Engine
    search_engine = SearchEngine(tenant_config, embedding_provider, sandbox)
    
    print("Indexing data...")
    await search_engine.index_all()
    print("Indexing complete.")
    
    # Check index size
    print(f"Emails index size: {len(search_engine.indices['emails']['vectors'])}")
    
    # Set user context (Test User)
    user_id = "user123" 
    search_engine.set_user_context(user_id)
    print(f"User Context: {user_id}")
    
    # Search
    query = "project alpha"
    print(f"Searching for: {query}")
    
    # Mock QueryAnalyzer
    mock_analyzer = MockQueryAnalyzer()
    
    # We need to import search_email from tools
    # But search_email is decorated, so we might need to access the underlying function or just call search_engine directly first
    # Let's call search_engine directly to be sure
    print("--- Direct Search Engine Test ---")
    results = await search_engine.search("emails", query, top_k=5)
    print(f"Direct Results found: {len(results)}")
    for res in results:
        print(f"Score: {res['score']}")
        print(f"Subject: {res['metadata']['subject']}")
        
    print("--- Tool Test ---")
    # To call the tool, we need to bypass the registry wrapper if it adds one, 
    # or just call the function if the decorator preserves it.
    # The registry decorator usually returns the wrapper.
    # Let's just trust the direct search engine test for now as it proves the core logic.
    
if __name__ == "__main__":
    asyncio.run(debug_search())
