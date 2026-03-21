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
from src.core.embedding_provider import AzureEmbeddingProvider, MockEmbeddingProvider, LocalEmbeddingProvider
from src.core.search_engine import SearchEngine
from src.core.tool_registry import registry
from src.sandbox.local_sandbox import LocalSandbox
import src.core.tools # Register tools

# Load env
load_dotenv()

# Page Config
st.set_page_config(page_title="EABench Agent", layout="wide")

def create_llm_from_config(model_config):
    provider = model_config.get("provider")
    name = model_config.get("name")
    temperature = model_config.get("parameters", {}).get("temperature", 0.0)

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            model=name,
            temperature=temperature
        )
    elif provider == "azure":
        api_key = os.getenv("AZURE_API_KEY")
        azure_endpoint = os.getenv("AZURE_ENDPOINT")
        api_version = os.getenv("AZURE_API_VERSION")
        return AzureOpenAIProvider(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            deployment_name=name,
            temperature=temperature
        )
    else:
        return MockLLMProvider()

@st.cache_resource
def get_global_resources(agent_config_path, tenant_config_path):
    # Load configs
    agent_config = AgentConfig.from_yaml(agent_config_path)
    tenant_config = TenantConfig.from_yaml(tenant_config_path)

    # Initialize LLM
    if agent_config.model.provider == ProviderType.OPENAI:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")
        llm = OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            model=agent_config.model.name,
            temperature=agent_config.model.parameters.get("temperature", 0.7)
        )
        
    elif agent_config.model.provider == ProviderType.AZURE:
        api_key = os.getenv("AZURE_API_KEY")
        azure_endpoint = os.getenv("AZURE_ENDPOINT")
        api_version = os.getenv("AZURE_API_VERSION")
        
        llm = AzureOpenAIProvider(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            deployment_name=agent_config.model.name,
            temperature=agent_config.model.parameters.get("temperature", 0.7)
        )
    else:
        llm = MockLLMProvider()

    # Initialize Embedding Provider
    embedding_provider = None
    if agent_config.embedding:
        if agent_config.embedding.provider == ProviderType.AZURE:
            api_key = os.getenv("AZURE_API_KEY")
            azure_endpoint = os.getenv("AZURE_ENDPOINT")
            emb_api_version = os.getenv("AZURE_EMB_API_VERSION") or os.getenv("AZURE_API_VERSION")
            
            embedding_provider = AzureEmbeddingProvider(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=emb_api_version,
                deployment_name=agent_config.embedding.model
            )
        elif agent_config.embedding.provider == ProviderType.LOCAL:
            embedding_provider = LocalEmbeddingProvider(model_name=agent_config.embedding.model)
    
    if not embedding_provider:
        # Fallback to Mock if not configured or unknown
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

# Sidebar - Configuration
st.sidebar.title("Configuration")

# Agent Config
agent_config_files = [f for f in os.listdir("examples/agents") if f.endswith(".yaml")]
selected_agent_config = st.sidebar.selectbox("Agent Config", agent_config_files, index=0 if agent_config_files else None)
agent_config_path = os.path.join("examples/agents", selected_agent_config) if selected_agent_config else "examples/agents/agent.yaml"

# Tenant Config
tenant_dirs = [d for d in os.listdir("examples/tenants") if os.path.isdir(os.path.join("examples/tenants", d))]
selected_tenant = st.sidebar.selectbox("Tenant", tenant_dirs, index=0 if tenant_dirs else None)
tenant_config_path = os.path.join("examples/tenants", selected_tenant, "tenant.yaml") if selected_tenant else "examples/tenants/test-tenant-1/tenant.yaml"

# Initialize Global Resources
try:
    tenant_config, sandbox, global_search_engine, llm, agent_config = get_global_resources(agent_config_path, tenant_config_path)
except Exception as e:
    st.error(f"Failed to initialize system: {e}")
    st.stop()

# Sidebar - Navigation
st.sidebar.title("Navigation")
app_mode = st.sidebar.radio("Go to", ["Chat", "Evaluation", "Side-by-Side Comparison", "Data Generator"])

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
    st.session_state.debug_logs = [] # Clear debug logs for new session
    st.session_state.last_user = current_user.username # Update last_user before rerun
    st.rerun()

if "last_user" not in st.session_state:
    st.session_state.last_user = current_user.username

runner = st.session_state.runner

if app_mode == "Chat":
    # Main Chat Interface
    st.title("EABench Agent Chat")

    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.debug_logs = [] # Initialize debug logs

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ask a question..."):
        # Clear debug logs for the new turn to avoid clutter
        st.session_state.debug_logs = []
        
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Run Agent
                    run_result = asyncio.run(runner.run(prompt, sandbox, session_search_engine))
                    response = run_result.response
                    st.markdown(response)
                    st.caption(f"Metrics: {run_result.metrics}")
                    st.session_state.messages.append({"role": "assistant", "content": response})
                except Exception as e:
                    st.error(f"Error: {e}")

    # Debug Logs Expander
    with st.expander("Debug Logs", expanded=False):
        if "debug_logs" in st.session_state and st.session_state.debug_logs:
            tab1, tab2 = st.tabs(["Reasoning Trace", "Search Analysis"])
            
            with tab1:
                for log in st.session_state.debug_logs:
                    if log['type'] in ["LLM Call", "LLM Response"]:
                        st.write(f"**{log['type']}**")
                        if log['type'] == "LLM Call":
                            with st.expander("Messages List"):
                                st.json(log['content'])
                        elif log['type'] == "LLM Response":
                            st.write(log['content'])
                            if log.get('tool_calls'):
                                st.write("Tool Calls:")
                                st.json(log['tool_calls'])
                        st.divider()
            
            with tab2:
                # Group Query Analysis with subsequent Tool Results
                logs = st.session_state.debug_logs
                i = 0
                while i < len(logs):
                    log = logs[i]
                    if log['type'] == "Query Analysis":
                        with st.container():
                            st.subheader(f"Search: {log['domain']}")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown("**Query Analysis**")
                                st.write(f"Input: `{log['query']}`")
                                st.json(log['result'])
                            
                            # Look ahead for the corresponding Tool Result
                            # It should be the next Tool Result with matching tool name
                            result_log = None
                            for j in range(i + 1, len(logs)):
                                if logs[j]['type'] == "Tool Result" and logs[j]['tool'] == log['domain']:
                                    result_log = logs[j]
                                    break
                            
                            with col2:
                                st.markdown("**Search Results**")
                                if result_log:
                                    st.code(result_log['result'], language="json")
                                else:
                                    st.write("No results found or tool execution failed.")
                            st.divider()
                    i += 1
        else:
            st.write("No logs yet.")

elif app_mode == "Evaluation":
    st.title("Agent Evaluation")
    
    import yaml
    from src.eval.models import EvaluationSet
    from src.eval.evaluator import Evaluator
    
    # Eval Prompts Selection
    st.subheader("1. Select Judge Prompts")
    prompt_files = [f for f in os.listdir("examples/evals") if f.endswith(".yaml")]
    selected_prompt_file = st.selectbox("Judge Config", prompt_files, index=0 if prompt_files else None)
    
    prompts = None
    judge_llm = llm # Default to agent's LLM

    if selected_prompt_file:
        try:
            with open(os.path.join("examples/evals", selected_prompt_file), 'r') as f:
                prompt_data = yaml.safe_load(f)
                prompts = prompt_data.get("prompts")
                
                # Check for model config override
                if "model" in prompt_data:
                    judge_llm = create_llm_from_config(prompt_data["model"])
                    st.info(f"Using custom judge model: {prompt_data['model'].get('name')} ({prompt_data['model'].get('provider')})")
                else:
                    st.info("Using default agent model as judge.")

        except Exception as e:
            st.error(f"Error loading prompts: {e}")

    # Eval Set Selection
    st.subheader("2. Upload Test Set")
    
    eval_set = None
    uploaded_file = st.file_uploader("Upload Test Set (YAML)", type="yaml")
    
    if uploaded_file is not None:
        try:
            data = yaml.safe_load(uploaded_file)
            eval_set = EvaluationSet(**data)
        except Exception as e:
            st.error(f"Error loading file: {e}")

    if eval_set and prompts:
        st.success(f"Ready to evaluate: {eval_set.name} ({len(eval_set.cases)} cases)")
        
        if st.button("Run Evaluation"):
            try:
                evaluator = Evaluator(runner, judge_llm, sandbox, session_search_engine, prompts=prompts)
                
                progress_bar = st.progress(0)
                results = []
                
                for i, case in enumerate(eval_set.cases):
                    with st.spinner(f"Evaluating Case {i+1}/{len(eval_set.cases)}: {case.query}"):
                        result = asyncio.run(evaluator.evaluate_single(case))
                        results.append(result)
                        progress_bar.progress((i + 1) / len(eval_set.cases))
                
                st.success("Evaluation Complete!")
                
                # Calculate Metrics
                total_cases = len(results)
                avg_citation = sum(r.metrics['citation_score'] for r in results) / total_cases if total_cases > 0 else 0
                avg_assertion = sum(r.metrics['assertion_score'] for r in results) / total_cases if total_cases > 0 else 0
                
                # Calculate Assertion Pass Rate
                total_assertions = 0
                passed_assertions = 0
                for r in results:
                    if r.assertion_results:
                        total_assertions += len(r.assertion_results)
                        passed_assertions += sum(1 for a in r.assertion_results if a.get('passed', False))
                
                assertion_pass_rate = passed_assertions / total_assertions if total_assertions > 0 else 0

                # Calculate Token/Tool Totals
                total_tool_calls = sum(r.metrics.get('tool_calls_count', 0) for r in results)
                total_prompt_tokens = sum(r.metrics.get('total_prompt_tokens', 0) for r in results)
                total_completion_tokens = sum(r.metrics.get('total_completion_tokens', 0) for r in results)

                # Display Metrics
                st.subheader("Overall Results")
                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric("Avg Citation Score", f"{avg_citation:.2f}")
                m_col2.metric("Avg Assertion Score", f"{avg_assertion:.2f}")
                m_col3.metric("Assertion Pass Rate", f"{passed_assertions}/{total_assertions} ({assertion_pass_rate:.0%})")
                
                m_col4, m_col5, m_col6 = st.columns(3)
                m_col4.metric("Total Tool Calls", f"{total_tool_calls}")
                m_col5.metric("Total Prompt Tokens", f"{total_prompt_tokens}")
                m_col6.metric("Total Completion Tokens", f"{total_completion_tokens}")

                # Download Button
                download_data = {
                    "overall_score_card": {
                        "total_cases": total_cases,
                        "avg_citation_score": float(f"{avg_citation:.2f}"),
                        "avg_assertion_score": float(f"{avg_assertion:.2f}"),
                        "assertion_pass_rate": f"{passed_assertions}/{total_assertions} ({assertion_pass_rate:.0%})",
                        "total_tool_calls": total_tool_calls,
                        "total_prompt_tokens": total_prompt_tokens,
                        "total_completion_tokens": total_completion_tokens
                    },
                    "detailed_results": []
                }

                for r in results:
                    r_dict = r.model_dump()
                    # Reorder assertion results for readability
                    if r_dict.get('assertion_results'):
                        reordered_assertions = []
                        for a in r_dict['assertion_results']:
                            # Ensure description is first
                            new_a = {'description': a.get('description', '')}
                            new_a.update({k: v for k, v in a.items() if k != 'description'})
                            reordered_assertions.append(new_a)
                        r_dict['assertion_results'] = reordered_assertions
                    download_data["detailed_results"].append(r_dict)

                yaml_output = yaml.dump(download_data, sort_keys=False, default_flow_style=False)
                
                st.download_button(
                    label="Download Results (YAML)",
                    data=yaml_output,
                    file_name="evaluation_results.yaml",
                    mime="application/x-yaml"
                )

                # Display Results
                st.subheader("Detailed Results")
                for res in results:
                    # Determine status symbol and text based on assertions
                    if res.assertion_results:
                        passed_count = sum(1 for a in res.assertion_results if a.get('passed'))
                        total_count = len(res.assertion_results)
                        
                        if passed_count == total_count:
                            status_symbol = "🟢"
                            status_label = "ALL PASSED"
                        elif passed_count == 0:
                            status_symbol = "🔴"
                            status_label = "ALL FAILED"
                        else:
                            status_symbol = "🟡"
                            status_label = "PARTIAL PASS"
                    else:
                        if res.passed:
                            status_symbol = "🟢"
                            status_label = "PASS"
                        else:
                            status_symbol = "🔴"
                            status_label = "FAIL"

                    with st.expander(f"{status_symbol} {status_label} - {res.query}", expanded=False):
                        col1, col2 = st.columns([2, 1])
                        with col1:
                            st.markdown("**Response:**")
                            st.info(res.response)
                            
                            st.markdown("**Assertions:**")
                            if res.assertion_results:
                                for assertion in res.assertion_results:
                                    status_color = "green" if assertion.get('passed') else "red"
                                    status_text = "PASS" if assertion.get('passed') else "FAIL"
                                    description = assertion.get('description', f"Assertion {assertion.get('id')}")
                                    reasoning = assertion.get('reasoning', '')
                                    
                                    st.markdown(f"**{description}**")
                                    st.markdown(f":{status_color}[{status_text}] - {reasoning}")
                                    st.divider()
                            else:
                                st.write("No detailed assertion results available.")

                            with st.expander("See Full Reasoning"):
                                st.markdown("**Overall Reasoning:**")
                                st.text(res.reasoning)

                        with col2:
                            st.metric("Citation Score", f"{res.metrics['citation_score']:.2f}")
                            st.metric("Assertion Score", f"{res.metrics['assertion_score']:.2f}")
                            st.metric("Latency", f"{res.metrics.get('latency', 0):.2f}s")
                            st.write("**Metrics:**")
                            st.json({k: v for k, v in res.metrics.items() if k not in ['citation_score', 'assertion_score', 'latency']})
                            st.write("**Tool Calls:**")
                            st.json(res.tool_calls)

            except Exception as e:
                st.error(f"Error running evaluation: {e}")

elif app_mode == "Side-by-Side Comparison":
    st.title("Side-by-Side Agent Comparison")
    
    import yaml
    from src.eval.models import EvaluationSet, ComparisonResult
    from src.eval.evaluator import Evaluator
    
    # Helper to create runner
    def create_runner_from_file(config_filename):
        path = os.path.join("examples/agents", config_filename)
        cfg = AgentConfig.from_yaml(path)
        
        # Create LLM
        if cfg.model.provider == ProviderType.OPENAI:
            l = OpenAIProvider(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_API_BASE"),
                model=cfg.model.name,
                temperature=cfg.model.parameters.get("temperature", 0.7)
            )
        elif cfg.model.provider == ProviderType.AZURE:
            l = AzureOpenAIProvider(
                api_key=os.getenv("AZURE_API_KEY"),
                azure_endpoint=os.getenv("AZURE_ENDPOINT"),
                api_version=os.getenv("AZURE_API_VERSION"),
                deployment_name=cfg.model.name,
                temperature=cfg.model.parameters.get("temperature", 0.7)
            )
        else:
            l = MockLLMProvider()
            
        return AgentRunner(cfg, l, registry)

    # 1. Select Agents
    st.subheader("1. Select Agents to Compare")
    col1, col2 = st.columns(2)
    
    agent_config_files = [f for f in os.listdir("examples/agents") if f.endswith(".yaml")]
    
    with col1:
        config_a_file = st.selectbox("Control (Agent A)", agent_config_files, index=0, key="agent_a")
    
    with col2:
        default_idx_b = 1 if len(agent_config_files) > 1 else 0
        config_b_file = st.selectbox("Treatment (Agent B)", agent_config_files, index=default_idx_b, key="agent_b")

    # 2. Select Judge
    st.subheader("2. Select Judge Prompts")
    prompt_files = [f for f in os.listdir("examples/evals") if f.endswith(".yaml")]
    selected_prompt_file = st.selectbox("Judge Config", prompt_files, index=0 if prompt_files else None, key="judge_sbs")
    
    prompts = None
    judge_llm = llm # Default to global LLM

    if selected_prompt_file:
        try:
            with open(os.path.join("examples/evals", selected_prompt_file), 'r') as f:
                prompt_data = yaml.safe_load(f)
                prompts = prompt_data.get("prompts")
                if "model" in prompt_data:
                    judge_llm = create_llm_from_config(prompt_data["model"])
                    st.info(f"Using custom judge model: {prompt_data['model'].get('name')}")
        except Exception as e:
            st.error(f"Error loading prompts: {e}")

    # 3. Upload Test Set
    st.subheader("3. Upload Test Set")
    eval_set = None
    uploaded_file = st.file_uploader("Upload Test Set (YAML)", type="yaml", key="sbs_upload")
    
    if uploaded_file is not None:
        try:
            data = yaml.safe_load(uploaded_file)
            eval_set = EvaluationSet(**data)
        except Exception as e:
            st.error(f"Error loading file: {e}")

    def render_agent_details(result, title):
        st.markdown(f"### {title}")
        st.info(result.response)
        
        st.markdown("**Metrics**")
        c_score = result.metrics.get('citation_score', 0.0)
        a_score = result.metrics.get('assertion_score', 0.0)
        latency = result.metrics.get('latency', 0.0)
        st.write(f"Citation Score: `{c_score:.2f}`")
        st.write(f"Assertion Score: `{a_score:.2f}`")
        st.write(f"Latency: `{latency:.2f}s`")
        
        with st.expander("More Metrics"):
            st.json({k: v for k, v in result.metrics.items() if k not in ['citation_score', 'assertion_score', 'latency']})
        
        st.markdown("**Assertions**")
        if result.assertion_results:
            for assertion in result.assertion_results:
                status_color = "green" if assertion.get('passed') else "red"
                status_text = "PASS" if assertion.get('passed') else "FAIL"
                description = assertion.get('description', '')
                reasoning = assertion.get('reasoning', '')
                
                st.markdown(f"**{description}**")
                st.markdown(f":{status_color}[{status_text}] {reasoning}")
                st.divider()
        else:
            st.caption("No assertion details.")

    if eval_set and prompts:
        if st.button("Run Comparison"):
            try:
                # Initialize Runners
                runner_a = create_runner_from_file(config_a_file)
                runner_b = create_runner_from_file(config_b_file)
                
                evaluator_a = Evaluator(runner_a, judge_llm, sandbox, session_search_engine, prompts=prompts)
                evaluator_b = Evaluator(runner_b, judge_llm, sandbox, session_search_engine, prompts=prompts)
                
                progress_bar = st.progress(0)
                comparison_results = []
                
                for i, case in enumerate(eval_set.cases):
                    with st.spinner(f"Comparing Case {i+1}/{len(eval_set.cases)}: {case.query}"):
                        # Run A
                        result_a = asyncio.run(evaluator_a.evaluate_single(case))
                        # Run B
                        result_b = asyncio.run(evaluator_b.evaluate_single(case))
                        
                        # Compare
                        comp_result = asyncio.run(evaluator_a.compare_two(case, result_a, result_b))
                        comparison_results.append(comp_result)
                        
                        progress_bar.progress((i + 1) / len(eval_set.cases))
                
                st.success("Comparison Complete!")
                
                # Calculate Stats
                wins_a = sum(1 for r in comparison_results if r.winner == "A")
                wins_b = sum(1 for r in comparison_results if r.winner == "B")
                ties = sum(1 for r in comparison_results if r.winner == "Tie")
                total = len(comparison_results)
                
                st.subheader("Overall Comparison")
                c1, c2, c3 = st.columns(3)
                c1.metric("Control Wins", f"{wins_a} ({wins_a/total:.0%})")
                c2.metric("Treatment Wins", f"{wins_b} ({wins_b/total:.0%})")
                c3.metric("Ties", f"{ties} ({ties/total:.0%})")
                
                st.divider()
                st.markdown("#### Metrics Analysis")
                
                # Citation Scores
                c_a = [r.result_a.metrics.get('citation_score', 0.0) for r in comparison_results]
                c_b = [r.result_b.metrics.get('citation_score', 0.0) for r in comparison_results]
                avg_c_a = sum(c_a)/len(c_a) if c_a else 0
                avg_c_b = sum(c_b)/len(c_b) if c_b else 0
                p_c = evaluator_a.calculate_p_value(c_a, c_b)
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Avg Citation (Control)", f"{avg_c_a:.2f}")
                col2.metric("Avg Citation (Treatment)", f"{avg_c_b:.2f}")
                col3.metric("Diff", f"{avg_c_b - avg_c_a:.2f}")
                col4.metric("P-Value", f"{p_c:.4f}" if p_c is not None else "N/A")
                
                # Assertion Scores
                a_a = [r.result_a.metrics.get('assertion_score', 0.0) for r in comparison_results]
                a_b = [r.result_b.metrics.get('assertion_score', 0.0) for r in comparison_results]
                avg_a_a = sum(a_a)/len(a_a) if a_a else 0
                avg_a_b = sum(a_b)/len(a_b) if a_b else 0
                p_a = evaluator_a.calculate_p_value(a_a, a_b)
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Avg Assertion (Control)", f"{avg_a_a:.2f}")
                col2.metric("Avg Assertion (Treatment)", f"{avg_a_b:.2f}")
                col3.metric("Diff", f"{avg_a_b - avg_a_a:.2f}")
                col4.metric("P-Value", f"{p_a:.4f}" if p_a is not None else "N/A")

                # Latency
                l_a = [r.result_a.metrics.get('latency', 0.0) for r in comparison_results]
                l_b = [r.result_b.metrics.get('latency', 0.0) for r in comparison_results]
                avg_l_a = sum(l_a)/len(l_a) if l_a else 0
                avg_l_b = sum(l_b)/len(l_b) if l_b else 0
                p_l = evaluator_a.calculate_p_value(l_a, l_b)
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Avg Latency (Control)", f"{avg_l_a:.2f}s")
                col2.metric("Avg Latency (Treatment)", f"{avg_l_b:.2f}s")
                col3.metric("Diff", f"{avg_l_b - avg_l_a:.2f}s")
                col4.metric("P-Value", f"{p_l:.4f}" if p_l is not None else "N/A")
                
                # Token/Tool Totals
                tc_a = sum(r.result_a.metrics.get('tool_calls_count', 0) for r in comparison_results)
                tc_b = sum(r.result_b.metrics.get('tool_calls_count', 0) for r in comparison_results)
                
                pt_a = sum(r.result_a.metrics.get('total_prompt_tokens', 0) for r in comparison_results)
                pt_b = sum(r.result_b.metrics.get('total_prompt_tokens', 0) for r in comparison_results)
                
                ct_a = sum(r.result_a.metrics.get('total_completion_tokens', 0) for r in comparison_results)
                ct_b = sum(r.result_b.metrics.get('total_completion_tokens', 0) for r in comparison_results)

                st.markdown("#### Resource Usage")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Tool Calls (Control)", f"{tc_a}")
                col2.metric("Total Tool Calls (Treatment)", f"{tc_b}")
                col3.metric("Diff", f"{tc_b - tc_a}")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Prompt Tokens (Control)", f"{pt_a}")
                col2.metric("Total Prompt Tokens (Treatment)", f"{pt_b}")
                col3.metric("Diff", f"{pt_b - pt_a}")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Completion Tokens (Control)", f"{ct_a}")
                col2.metric("Total Completion Tokens (Treatment)", f"{ct_b}")
                col3.metric("Diff", f"{ct_b - ct_a}")

                # Download Results
                download_data = {
                    "summary": {
                        "control_agent": config_a_file,
                        "treatment_agent": config_b_file,
                        "wins_control": wins_a,
                        "wins_treatment": wins_b,
                        "ties": ties,
                        "total": total,
                        "metrics": {
                            "citation": {
                                "control": avg_c_a,
                                "treatment": avg_c_b,
                                "diff": avg_c_b - avg_c_a,
                                "p_value": p_c
                            },
                            "assertion": {
                                "control": avg_a_a,
                                "treatment": avg_a_b,
                                "diff": avg_a_b - avg_a_a,
                                "p_value": p_a
                            },
                            "latency": {
                                "control": avg_l_a,
                                "treatment": avg_l_b,
                                "diff": avg_l_b - avg_l_a,
                                "p_value": p_l
                            },
                            "resource_usage": {
                                "tool_calls": {"control": tc_a, "treatment": tc_b, "diff": tc_b - tc_a},
                                "prompt_tokens": {"control": pt_a, "treatment": pt_b, "diff": pt_b - pt_a},
                                "completion_tokens": {"control": ct_a, "treatment": ct_b, "diff": ct_b - ct_a}
                            }
                        }
                    },
                    "detailed_comparisons": [r.model_dump() for r in comparison_results]
                }
                
                yaml_output = yaml.dump(download_data, sort_keys=False, default_flow_style=False)
                st.download_button(
                    label="Download Comparison (YAML)",
                    data=yaml_output,
                    file_name="comparison_results.yaml",
                    mime="application/x-yaml"
                )
                
                # Display Detailed Results
                st.subheader("Detailed Comparisons")
                for res in comparison_results:
                    winner_color = "green" if res.winner == "A" else "blue" if res.winner == "B" else "grey"
                    with st.expander(f"Winner: :{winner_color}[{res.winner}] - {res.query}", expanded=False):
                        st.write(f"**Reasoning:** {res.reasoning}")
                        st.write(f"**Score:** {res.score}")
                        
                        col_a, col_b = st.columns(2)
                        with col_a:
                            render_agent_details(res.result_a, f"Control ({config_a_file})")
                        with col_b:
                            render_agent_details(res.result_b, f"Treatment ({config_b_file})")

            except Exception as e:
                st.error(f"Error running comparison: {e}")

elif app_mode == "Data Generator":
    st.title("Data Generator")
    st.markdown("Generate a new test tenant based on a custom story.")

    # Get available prompt configs
    prompt_files = [f for f in os.listdir("examples/generation") if f.endswith(".yaml")]
    default_prompt_index = 0
    if "default_prompts.yaml" in prompt_files:
        default_prompt_index = prompt_files.index("default_prompts.yaml")

    with st.form("data_gen_form"):
        col1, col2 = st.columns(2)
        with col1:
            company_name = st.text_input("Company Name", value="TechNova")
            industry = st.text_input("Industry", value="Software")
            company_size = st.selectbox("Company Size", ["small", "medium", "large"], index=1)
            prompts_file = st.selectbox("Prompts Config", prompt_files, index=default_prompt_index)
        
        with col2:
            duration_days = st.number_input("Duration (Days)", min_value=1, max_value=30, value=7)
            # provider = st.selectbox("LLM Provider", ["openai", "azure"], index=0) # Removed in favor of yaml config
        
        key_events_str = st.text_area("Key Events (one per line)", value="Project Alpha Kickoff\nServer Outage Incident")
        description = st.text_area("Description", value="A fast-paced software startup facing scaling challenges.")
        
        submitted = st.form_submit_button("Generate Tenant")

    if submitted:
        from src.generator.pipeline import DataGenerator
        from src.generator.models import StoryConfig
        
        # Parse events
        key_events = [e.strip() for e in key_events_str.split("\n") if e.strip()]
        
        story = StoryConfig(
            company_name=company_name,
            industry=industry,
            company_size=company_size,
            duration_days=duration_days,
            key_events=key_events,
            description=description
        )
        
        # Initialize LLM for Generator (reuse global config logic or create new)
        # We need to create a new LLM instance based on the selected provider in the form
        # independent of the agent's LLM
        
        prompts_path = os.path.join("examples/generation", prompts_file)
        with open(prompts_path, "r") as f:
            prompts_config = yaml.safe_load(f)
            
        model_config = prompts_config.get("model_config", {})
        final_provider = model_config.get("provider", "openai")
        final_model = model_config.get("model")

        if final_provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                st.error("OPENAI_API_KEY not found in environment variables.")
                st.stop()
                
            gen_llm = OpenAIProvider(
                api_key=api_key,
                base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE"),
                model=final_model or os.getenv("OPENAI_MODEL", "gpt-4o")
            )
        else:
            api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_ENDPOINT")
            deployment = final_model or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_DEPLOYMENT_NAME")
            api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("AZURE_API_VERSION") or "2023-05-15"

            if not api_key or not endpoint:
                st.error("AZURE_OPENAI_API_KEY (or AZURE_API_KEY) and AZURE_OPENAI_ENDPOINT (or AZURE_ENDPOINT) are required.")
                st.stop()
            
            if not deployment:
                st.error("AZURE_OPENAI_DEPLOYMENT_NAME (or AZURE_DEPLOYMENT_NAME) is missing in .env and not specified in prompts yaml.")
                st.stop()
                
            gen_llm = AzureOpenAIProvider(
                api_key=api_key,
                azure_endpoint=endpoint,
                deployment_name=deployment,
                api_version=api_version
            )
            
        generator = DataGenerator(gen_llm, prompts_path=prompts_path)
        
        with st.spinner("Generating data... This may take a minute."):
            try:
                # Run async generation
                output = asyncio.run(generator.generate_tenant(story))
                
                st.success("Generation Complete!")
                st.write(f"**Tenant ID:** `{output.tenant_id}`")
                st.write(f"**Path:** `{output.base_path}`")
                st.write(f"**Summary:** {output.summary}")
                st.info("Refresh the page to see the new tenant in the configuration sidebar.")
                
            except Exception as e:
                st.error(f"Generation failed: {e}")

