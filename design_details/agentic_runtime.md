# Agentic Runtime and Configurability

## Overview

EABench's agentic runtime is a fully configurable, YAML-driven enterprise agent framework designed for **evaluation-time reproducibility**. Every aspect of the agent—the reasoning model, embedding model, cognitive architecture, system prompt, tool set, and query-analysis strategies—is declared in a single YAML file. This makes it straightforward to swap models, architectures, or prompt strategies without touching application code.

The runtime is implemented in `python/src/core/` with the following key modules:

| Module | Responsibility |
|---|---|
| `agent_config.py` | Pydantic models that parse agent YAML files |
| `agent_runner.py` | The main ReAct / plan-and-execute execution loop |
| `tool_registry.py` | Decorator-based tool registration |
| `tools.py` | Built-in tool implementations |
| `search_engine.py` | Semantic vector search over tenant data |
| `query_analyzer.py` | LLM-driven query refinement layer |
| `llm_provider.py` | Abstract LLM interface |
| `provider_factory.py` | Factory for OpenAI / Azure OpenAI providers |
| `embedding_provider.py` | Embedding API abstraction |

---

## Agent Configuration Schema

An agent is described by a YAML file. The full schema is:

```yaml
id:       <string>          # Unique identifier for this agent variant
version:  <string>          # Semver for reproducibility

model:
  provider: azure | openai | anthropic | local
  name:     <deployment or model name>
  parameters:
    temperature: <float>
    # any other provider-specific parameters

embedding:
  provider: azure | openai
  model:    <embedding model name>
  parameters: {}

system_prompt: |
  <multi-line prompt with {user_profile} placeholder>

planning_prompt: |             # only used for researcher (plan-and-execute) strategy
  <multi-line planning prompt>

query_analyzer_prompt:
  search_email:   |<prompt>
  search_file:    |<prompt>
  search_chat:    |<prompt>
  search_meeting: |<prompt>
  search_people:  |<prompt>

tools:
  definitions:
    - read_file
    - execute_python
    - search_file
    - search_email
    - search_chat
    - search_group_chat
    - search_channel
    - search_meeting
    - search_people
    - search_in_file

flow:
  strategy: react | researcher   # cognitive architecture
  max_turns: <int>               # hard cap on reasoning turns
```

Three reference configurations are provided under `examples/agents/`:

| File | Strategy | Max Turns | Model | Notes |
|---|---|---|---|---|
| `react_agent.yaml` | `react` | 5 | gpt-4o (temp 0.7) | Standard ReAct agent |
| `react_agent_v2.yaml` | `react` | 5 | gpt-4o (temp 0.5) | More concise prompts |
| `researcher_agent.yaml` | `researcher` | 10 | gpt-4o-mini (temp 0.0) | Plan-and-execute |

---

## Cognitive Architectures

### ReAct (Reason + Act)

`FlowStrategy.REACT` is the default architecture. The agent loops until it produces a final answer or hits `max_turns`:

```
System prompt (with injected user profile)
  └─► User query
        └─► [LLM generates thought + tool call]
              └─► [Tool executes, result appended to history]
                    └─► [LLM generates next thought or final answer]
```

**Turn management**: Each call to the LLM that results in a tool call increments the turn counter. When the LLM produces a message with *no* tool calls, it is treated as the final response. If `max_turns` is reached without a final answer, `MaxTurnsExceededError` is raised.

### Plan-and-Execute (Researcher)

`FlowStrategy.RESEARCHER` adds a planning phase before the ReAct loop:

1. A separate *planner* LLM call (no tools available) generates a step-by-step research plan from the user query and user profile.
2. The plan is injected into the conversation as context before the user query.
3. The agent executes the plan using the normal ReAct loop.

This architecture is particularly effective for multi-hop queries because the planner can reason about the full dependency chain upfront, then the executor follows the plan systematically.

```
Planning call (no tools):
  Input:  user_query + user_profile
  Output: numbered research plan

Execution loop (tools enabled):
  Input:  "Original Request: {query}\nResearch Plan:\n{plan}\nPlease execute..."
  Loop:   ReAct until final answer
```

---

## LLM Provider

The `LLMProvider` abstract class defines the interface:

```python
class LLMProvider:
    async def generate(self, messages: List[Message], tools: List[dict]) -> Message:
        ...
    async def get_completion(self, messages: List[dict]) -> str:
        ...
```

Concrete implementations:
- `OpenAIProvider`: Direct OpenAI API (supports `base_url` override for compatible endpoints)
- `AzureOpenAIProvider`: Azure-hosted deployments with API key + endpoint configuration

Provider selection is driven entirely by the `model.provider` field in the agent YAML. The `provider_factory.py` module instantiates the correct class at runtime based on environment variables:

| Env Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key |
| `AZURE_OPENAI_API_KEY` | Azure API key |
| `AZURE_OPENAI_ENDPOINT` | Azure endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Azure deployment name |
| `AZURE_OPENAI_API_VERSION` | API version (default: `2023-05-15`) |

---

## Tool System

Tools are registered via a decorator pattern:

```python
@registry.register(name="read_file", args_schema=ReadFileInput)
def read_file(path: str, sandbox: SandboxInterface) -> str:
    """Reads the content of a file from the sandbox."""
    return sandbox.read_file(path)
```

The `ToolRegistry` converts registered functions to OpenAI-compatible JSON schemas for tool-calling. At runtime, `AgentRunner` filters the global registry to only the tools listed in `tools.definitions` of the active agent config.

### Built-in Tools

| Tool | Description |
|---|---|
| `read_file` | Read full file content from the sandbox |
| `search_in_file` | Keyword search within a specific file |
| `list_files` | List files in a sandbox directory |
| `execute_python` | Execute Python code (sandboxed); stdout/stderr captured |
| `execute_command` | Execute a shell command (sandboxed) |
| `search_email` | Semantic search over indexed emails |
| `search_file` | Semantic search over file snippets or full content |
| `search_chat` | Semantic search over 1:1 chat messages |
| `search_group_chat` | Semantic search over group chat messages |
| `search_channel` | Semantic search over channel posts |
| `search_meeting` | Semantic search over meeting metadata or transcripts |
| `search_people` | Semantic search over user profiles |

### Dependency Injection

Tool functions declare their dependencies as function parameters. The runner injects them at call time:

```python
if "sandbox" in sig.parameters:       kwargs["sandbox"] = sandbox
if "search_engine" in sig.parameters: kwargs["search_engine"] = search_engine
if "llm" in sig.parameters:           kwargs["llm"] = self.llm
if "query_analyzer" in sig.parameters: kwargs["query_analyzer"] = self.query_analyzer
```

This keeps tool implementations clean and testable without a dependency injection framework.

---

## Search Stack

The `SearchEngine` maintains separate in-memory **vector indices** for each data type:

| Index | Contents |
|---|---|
| `file_snippets` | File path + snippet text |
| `file_contents` | Full file content (from sandbox) |
| `emails` | From/To/CC/BCC + subject + body |
| `chats` | Per-message chat entries |
| `group_chats` | Per-message group chat entries |
| `channels` | Per-post channel entries |
| `meetings_config` | Meeting metadata (title, agenda, attendees) |
| `meetings_transcript` | Full meeting transcripts |
| `users` | Profile fields (name, title, department, skills) |

Similarity search uses **cosine similarity** computed with NumPy. All vectors for a tenant are precomputed at startup (`index_all()`) in batched, concurrent embedding API calls (batch size: 512, concurrency: 8).

**Caching**: Computed indices are serialised to `{tenant_root}/.cache/embeddings_{model_name}.pkl` and reloaded on subsequent runs, eliminating redundant embedding API calls.

### Access Control

`SearchEngine._is_user_allowed()` enforces per-user visibility:
- **Emails**: only visible if `current_user_id` is sender, recipient, CC, or BCC
- **Chats / Group Chats / Channels**: only visible if user is a participant
- **Meetings**: only visible if user is organiser, invitee, or attendee
- **Files / People**: visible to all users (open by default)

The `user_id` context is set on the engine before each evaluation case runs: `search_engine.set_user_context(case.user_id)`.

---

## Query Analyzer

The `QueryAnalyzer` is an optional LLM-driven pre-processing layer that refines raw tool queries before they hit the vector index. It is activated when the `query_analyzer_prompt` section is present in the agent YAML.

For each search tool, a per-tool prompt template instructs the LLM to classify the query and select an optimal strategy:

```yaml
query_analyzer_prompt:
  search_email: |
    Analyze the email search query: "{query}"
    ...
    Return JSON:
    - "strategy": "recent" | "semantic" | "sender_filter" | "hybrid"
    - "refined_query": optimised query string
    - "sender_name": resolved user ID for sender filtering
```

The analyzer outputs a strategy and a refined query that `SearchEngine.search()` uses to apply appropriate filters (sender matching, recency sorting, etc.) before returning results.

---

## User Profile Injection

At the start of each evaluation run, the agent's system prompt is personalised by replacing the `{user_profile}` placeholder with the JSON-serialised profile of the requesting user:

```python
user_profile_str = user.model_dump_json(indent=2)
system_prompt = system_prompt.replace("{user_profile}", user_profile_str)
```

This gives the agent full context about the current user's role, manager, department, and skills, enabling accurate pronoun resolution ("my manager" → `manager_id`) and relationship reasoning.

---

## Metrics Collection

`AgentRunner` accumulates fine-grained usage metrics during a run and returns them alongside the response:

```python
metrics = {
    "tool_calls_count":         int,
    "llm_calls_count":          int,
    "total_prompt_tokens":      int,
    "total_completion_tokens":  int,
    "avg_prompt_tokens":        float,
    "avg_completion_tokens":    float,
}
```

These are passed through to the evaluation harness and recorded in the result JSON.

---

## Extensibility

### Adding a New Tool

1. Write a function with the desired signature.
2. Define an input schema as a Pydantic `BaseModel`.
3. Decorate with `@registry.register(name="...", args_schema=...)`.
4. Add the tool name to `tools.definitions` in the agent YAML.

No code changes are needed in `AgentRunner` or `SearchEngine`.

### Adding a New LLM Provider

1. Subclass `LLMProvider` and implement `generate()` and `get_completion()`.
2. Add the provider to `ProviderType` enum in `agent_config.py`.
3. Handle the new enum value in `provider_factory.py`.

### Adding a New Cognitive Architecture

1. Add a value to `FlowStrategy` enum.
2. Add a branch in `AgentRunner.run()` before the ReAct loop.
