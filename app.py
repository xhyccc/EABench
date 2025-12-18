import streamlit as st
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

# Load env
load_dotenv()

# Page Config
st.set_page_config(page_title="EABench Agent", layout="wide")

@st.cache_resource
def get_global_resources():
    # Load configs
    agent_config = AgentConfig.from_yaml("examples/agent.yaml")
    tenant_config = TenantConfig.from_yaml("examples/tenants/test-tenant-1/tenant.yaml")

    # Initialize components
    if agent_config.model.provider == ProviderType.OPENAI:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")
        llm = OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            model=agent_config.model.name,
            temperature=agent_config.model.parameters.get("temperature", 0.7)
        )
        embedding_provider = MockEmbeddingProvider()
        
    elif agent_config.model.provider == ProviderType.AZURE:
        api_key = os.getenv("AZURE_API_KEY")
        azure_endpoint = os.getenv("AZURE_ENDPOINT")
        api_version = os.getenv("AZURE_API_VERSION")
        emb_api_version = os.getenv("AZURE_EMB_API_VERSION")
        
        llm = AzureOpenAIProvider(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            deployment_name=agent_config.model.name,
            temperature=agent_config.model.parameters.get("temperature", 0.7)
        )
        
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
    sandbox.start() # Start the sandbox
    
    # Global Search Engine (holds the indices)
    search_engine = SearchEngine(tenant_config, embedding_provider, sandbox)
    
    # Index immediately
    print("Indexing data...")
    asyncio.run(search_engine.index_all())
    print("Indexing complete.")
    
    return tenant_config, sandbox, search_engine, llm, agent_config

# Initialize Global Resources
try:
    tenant_config, sandbox, global_search_engine, llm, agent_config = get_global_resources()
except Exception as e:
    st.error(f"Failed to initialize system: {e}")
    st.stop()

# Sidebar - User Selection
st.sidebar.title("Login")
# Create a mapping of "Display Name (username)" -> User Object
user_options = {f"{u.profile.name.display_name} ({u.username})": u for u in tenant_config.users}
selected_label = st.sidebar.selectbox("Select User", list(user_options.keys()))
current_user = user_options[selected_label]

st.sidebar.write(f"**Logged in as:** {current_user.profile.name.display_name}")
st.sidebar.write(f"**Role:** {current_user.profile.title}")
st.sidebar.write(f"**User ID:** {current_user.id}")

# Session-specific Search Engine (shares indices, but has own user context)
session_search_engine = SearchEngine(
    tenant_config, 
    global_search_engine.embedding_provider, 
    sandbox, 
    indices=global_search_engine.indices
)
session_search_engine.set_user_context(current_user.id)

# Session-specific Agent Runner
if "runner" not in st.session_state:
    st.session_state.runner = AgentRunner(agent_config, llm, registry)

# Reset runner if user changed
if "last_user" in st.session_state and st.session_state.last_user != current_user.username:
    st.session_state.runner = AgentRunner(agent_config, llm, registry)
    st.session_state.messages = []
    st.rerun()

st.session_state.last_user = current_user.username
runner = st.session_state.runner

# Main Chat Interface
st.title("EABench Agent Chat")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask a question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                # Run Agent
                response = asyncio.run(runner.run(prompt, sandbox, session_search_engine))
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            except Exception as e:
                st.error(f"Error: {e}")

# Debug Logs Expander
with st.expander("Debug Logs", expanded=False):
    if "debug_logs" in st.session_state:
        for log in st.session_state.debug_logs:
            st.write(f"**{log['type']}**")
            if log['type'] == "LLM Call":
                st.json(log['content'])
            elif log['type'] == "LLM Response":
                st.write(log['content'])
                if log.get('tool_calls'):
                    st.write("Tool Calls:")
                    st.json(log['tool_calls'])
            elif log['type'] == "Tool Call":
                st.write(f"Tool: `{log['tool']}`")
                st.json(log['arguments'])
            elif log['type'] == "Tool Result":
                st.write(f"Tool: `{log['tool']}`")
                st.code(log['result'])
            st.divider()
    else:
        st.write("No logs yet.")
