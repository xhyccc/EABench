import asyncio
import os
from dotenv import load_dotenv
from src.config.agent_config import AgentConfig, ProviderType
from src.config.tenant_config import TenantConfig
from src.core.agent_runner import AgentRunner
from src.core.llm_provider import MockLLMProvider
from src.core.openai_provider import OpenAIProvider
from src.core.azure_provider import AzureOpenAIProvider
from src.core.embedding_provider import AzureEmbeddingProvider, MockEmbeddingProvider
from src.core.search_engine import SearchEngine
from src.core.tool_registry import registry
from src.sandbox.local_sandbox import LocalSandbox
import src.core.tools # Register tools

load_dotenv()

async def main():
    # Load configs
    agent_config = AgentConfig.from_yaml("examples/agent.yaml")
    tenant_config = TenantConfig.from_yaml("examples/tenants/test-tenant-1/tenant.yaml")

    # Initialize components
    if agent_config.model.provider == ProviderType.OPENAI:
        api_key = os.getenv("SILICONFLOW_API_KEY")
        base_url = os.getenv("SILICONFLOW_API_ENDPOINT")
        if not api_key or not base_url:
            raise ValueError("SILICONFLOW_API_KEY and SILICONFLOW_API_ENDPOINT must be set in .env")
            
        llm = OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            model=agent_config.model.name,
            temperature=agent_config.model.parameters.get("temperature", 0.7)
        )
        # For now, use MockEmbeddingProvider if not Azure
        embedding_provider = MockEmbeddingProvider()
        
    elif agent_config.model.provider == ProviderType.AZURE:
        api_key = os.getenv("AZURE_API_KEY")
        azure_endpoint = os.getenv("AZURE_ENDPOINT")
        api_version = os.getenv("AZURE_API_VERSION")
        emb_api_version = os.getenv("AZURE_EMB_API_VERSION")
        
        if not api_key or not azure_endpoint or not api_version:
            raise ValueError("AZURE_API_KEY, AZURE_ENDPOINT, and AZURE_API_VERSION must be set in .env")
            
        llm = AzureOpenAIProvider(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            deployment_name=agent_config.model.name,
            temperature=agent_config.model.parameters.get("temperature", 0.7)
        )
        
        # Initialize Embedding Provider
        # Assuming deployment name for embedding is 'text-embedding-ada-002' or similar
        # You might want to add this to config or env
        embedding_deployment = "text-embedding-ada-002" 
        embedding_provider = AzureEmbeddingProvider(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=emb_api_version or api_version,
            deployment_name=embedding_deployment
        )
    else:
        llm = MockLLMProvider()
        embedding_provider = MockEmbeddingProvider()

    sandbox = LocalSandbox(tenant_config)
    
    # Initialize Search Engine
    search_engine = SearchEngine(tenant_config, embedding_provider, sandbox)
    
    runner = AgentRunner(agent_config, llm, registry)

    print(f"Starting agent {agent_config.id} in sandbox for tenant {tenant_config.id}...")
    
    try:
        sandbox.start()
        
        # Index data
        print("Indexing tenant data...")
        await search_engine.index_all()
        print("Indexing complete.")
        
        # Run a query
        query = "What was the critical issue with Project Alpha and how was it resolved?"
        print(f"User: {query}")
        
        response = await runner.run(query, sandbox, search_engine)
        print(f"Agent: {response}")
        
    finally:
        sandbox.stop()
        print("Sandbox cleaned up.")

if __name__ == "__main__":
    asyncio.run(main())
