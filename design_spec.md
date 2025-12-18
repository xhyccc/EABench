# **Comprehensive Technical Specification for a Modular, LLM-Agnostic Agent Execution and Evaluation Platform**

## **1\. Architectural Philosophy and System Imperatives**

The transition from static software systems to probabilistic, agentic architectures represents a fundamental paradigm shift in enterprise application development. As organizations move beyond simple retrieval-augmented generation (RAG) toward autonomous agents capable of multi-step reasoning, tool execution, and environment manipulation, the infrastructure supporting these systems must evolve. The current landscape of agent development is fragmented, often characterized by tightly coupled implementations where the reasoning engine (the Large Language Model or LLM), the execution environment, and the evaluation logic are intertwined. This coupling renders systems brittle to model updates, difficult to test rigorously, and unsafe for production deployment.

This report outlines the technical specification for a Python-based **Agent Execution and Evaluation Platform** designed to address these challenges through strict modularity, isolation, and observability. The proposed architecture is grounded in the principle of **Model Agnosticism**, ensuring that the reasoning core can be interchanged without refactoring the surrounding infrastructure. It enforces **Configuration-as-Code**, where agent behaviors, tools, and workflows are defined in declarative schemas rather than imperative code. Furthermore, it mandates **Sandboxed Execution** for all tool interactions, ensuring security and reproducibility, and implements a comprehensive **Observability-Driven Evaluation** framework that assesses not just the final output, but the validity of the execution trace itself.

### **1.1 The Necessity of Decoupling in Agentic Systems**

In traditional software engineering, the logic governing state transitions is deterministic and explicitly codified by the developer. In agentic systems, this logic is offloaded to a probabilistic model (the LLM) which interprets natural language instructions to select tools and determine control flow. This introduces significant non-determinism. If the infrastructure wrapping the agent is tightly coupled to a specific model provider (e.g., assuming OpenAI’s function-calling schema), switching to a different model (e.g., Anthropic’s Claude or an open-source Llama 3\) requires extensive rewriting of the tool execution layer.

To mitigate this, the proposed platform implements a **Gateway-Adapter Pattern**. The core runtime interacts with an abstract LLMProvider interface. Concrete adapters—whether for proprietary APIs or local inference servers like Ollama—translate the platform’s standardized internal representation of "messages" and "tool definitions" into the specific format required by the endpoint. This allows for the dynamic configuration of LLMs at runtime, satisfying the requirement for independence and configurability.1

### **1.2 Security-First Execution Environments**

The capability of agents to perform "file operations in a dedicated folder" and execute "CLI commands" presents acute security risks, including privilege escalation, data exfiltration, and destructive file manipulation. Relying on prompt engineering ("Please do not delete system files") is insufficient for security. The platform therefore enforces isolation at the infrastructure level. Every agent session is encapsulated within a **Test Tenant**—a logical construct that maps to a physical isolation boundary, such as an ephemeral Docker container or a restricted user namespace. This ensures that the "dedicated folder" is cryptographically isolated from the host system and other concurrent tenants, enabling safe multi-tenant testing.3

### **1.3 The Evaluation Gap: From Output to Process**

Standard evaluation metrics used in NLP (BLEU, ROUGE) or simple unit tests are inadequate for agents. An agent might produce the correct final answer but arrive at it through flawed reasoning or by making redundant, costly tool calls. The evaluation framework specified here adopts a **Trace-Centric Approach**. By leveraging OpenTelemetry standards to capture the full execution graph—including thoughts, tool arguments, and system observations—the platform enables "LLM-as-a-Judge" evaluators to scrutinize the *process*. This allows for nuanced metrics such as "Step Efficiency," "Plan Adherence," and "Citation Faithfulness," ensuring that the agent operates reliably and efficiently.5

## ---

**2\. Core Agent Runtime Architecture**

The Agent Runtime is the orchestration engine responsible for hydrating an agent from its configuration, managing its state, and facilitating the recursive loop of reasoning and acting. It is built on Python 3.10+ to leverage modern typing and asynchronous capabilities, ensuring high throughput for I/O-bound tool operations.

### **2.1 The Configuration Schema: Defining Agency as Data**

To satisfy the requirement that the agent be "configurable (tools, prompts, flows)," the platform rejects the pattern of defining agents as Python classes. Instead, agents are defined as data objects, serialized in YAML. This aligns with emerging standards like the "Open Agent Specification" 7 and Mozilla’s AgentConfig 8, which facilitate portability and version control.

The configuration schema is divided into four primary sections: **Meta**, **Model**, **Capabilities**, and **Workflow**.

#### **2.1.1 The Agent Definition Schema**

The agent.yaml file serves as the single source of truth for an agent's behavior. The Meta section contains identifiers and versioning information, which are crucial for tracking performance regression over time. The Model section defines the reasoning engine, specifying the provider alias and model parameters (temperature, top\_p, stop sequences). Crucially, the provider string (e.g., openai, ollama\_local) dictates which adapter class is loaded at runtime.

The Capabilities section lists the enabled tools. Rather than implementing tools within the agent, the configuration references tools registered in the platform's ToolRegistry. Each tool entry can define override parameters, such as specific allowed directories or read-only flags, allowing the same underlying Python function to be reused across different agents with varying permission levels.

**Table 1: Agent Configuration Schema Components**

| Section | Parameter | Type | Description |
| :---- | :---- | :---- | :---- |
| **Meta** | id | String | Unique identifier for the agent (e.g., devops-assistant-v1). |
|  | version | String | Semantic versioning of the configuration. |
| **Model** | provider | Enum | The backend to use (openai, anthropic, local). |
|  | name | String | Specific model identifier (e.g., gpt-4-turbo, llama3). |
|  | parameters | Dict | Hyperparameters for generation (temperature, max\_tokens). |
| **Context** | system\_prompt | String | The static instruction set defining persona and constraints. |
|  | dynamic\_keys | List | Context variables injected at runtime (e.g., user\_id, cwd). |
| **Tools** | definitions | List | References to registered tools (e.g., file\_system, cli). |
|  | config | Dict | Tool-specific constraints (e.g., root\_dir: /workspace). |
| **Flow** | strategy | Enum | Execution pattern: react, chain, planning\_dag. |
|  | max\_turns | Integer | Safety limit to prevent infinite loops. |

This declarative approach allows for A/B testing different prompts or model configurations simply by passing a different YAML file to the runner, without altering the application code.

### **2.2 The LLM Abstraction Layer**

The requirement for LLM independence mandates an **Interface Adapter** architecture. The core runtime interacts exclusively with an abstract base class, LLMProvider, which defines the contract for text generation and structured function calling.

The LLMProvider enforces a normalized input format, accepting a list of Message objects (System, User, Assistant, Tool). The concrete implementation of the adapter is responsible for transforming this normalized list into the proprietary format of the backend API. For instance, the OpenAIAdapter will serialize tool definitions into the tools JSON schema, while the AnthropicAdapter might format them into XML structures if using older Claude models, or the tool\_use blocks for newer ones. This isolation ensures that if a provider changes their API specification, the breakage is contained within the adapter, leaving the agent logic untouched.1

#### **2.2.1 Handling Tool Call Variations**

A significant challenge in LLM agnosticism is the variability in how models request tool executions. Some models output strictly formatted JSON, while others may output markdown-wrapped code blocks. The Abstraction Layer includes a **Output Parser** component. This parser validates the raw output against the expected schema. If the model fails to generate valid JSON (common in smaller local models), the parser can trigger a "Repair Loop," feeding the error back to the model and requesting a correction. This ensures that the agent runtime always receives a structured ToolCall object, regardless of the model's native capability.9

### **2.3 The Tool Registry and Execution Engine**

The agent requires access to "basic functions like CLI, file operations." These capabilities are implemented as Python functions decorated with @tool, similar to patterns seen in LangChain and PydanticAI.2

#### **2.3.1 Structured Tool Definitions**

The @tool decorator utilizes Pydantic models to inspect the function signature and automatically generate the JSON Schema required by the LLM. This ensures that the tool's description and parameter types are always synchronized with the code.

Python

from pydantic import BaseModel, Field  
from typing import Optional

class FileReadInput(BaseModel):  
    path: str \= Field(..., description="The relative path to the file to read.")  
    encoding: str \= Field("utf-8", description="File encoding.")

@tool(name="read\_file", args\_schema=FileReadInput)  
def read\_file(path: str, encoding: str \= "utf-8") \-\> str:  
    """Reads the content of a file from the allowed workspace."""  
    \# Implementation details...

#### **2.3.2 The CLI Tool Implementation**

The CLI tool allows the agent to execute system commands. To adhere to the security requirements, this tool does not simply call os.system. Instead, it proxies the command to the configured **Sandbox Environment**. This decoupling means the agent code "thinks" it is running a command, but the execution actually occurs inside an isolated container or a restricted user namespace, preventing any damage to the host.3

### **2.4 Flow Orchestration: From Chains to Graphs**

The "flow" configuration determines how the agent transitions between reasoning, acting, and observing. While simple agents use a linear loop (ReAct), complex tasks often require more structured behavior. The platform incorporates a **State Graph** engine, conceptually similar to LangGraph 12, to manage these flows.

#### **2.4.1 ReAct Loop Strategy**

The default react strategy implements the classic "Reason-Act" loop. The agent receives the current history, generates a thought and a tool call, executes the tool, receives the output, and repeats. This continues until the LLM generates a "Final Answer" token or the max\_turns limit is reached. This is ideal for open-ended exploration.14

#### **2.4.2 Directed Acyclic Graph (DAG) Strategy**

For workflows requiring specific compliance checks or multi-stage planning, the dag strategy forces the agent through a predefined set of nodes. For example, a "Code Writer" flow might force a transition from Write Code to Run Tests to Refactor, preventing the agent from claiming success before the tests pass. The configuration defines the nodes and the conditional edges (e.g., if test\_result \== fail, goto Refactor). This structured approach is essential for ensuring reliability in enterprise scenarios.15

## ---

**3\. Sandboxing and Tenant Isolation Infrastructure**

To satisfy the requirements for "test tenant" configurability and "file operations in a dedicated folder," the platform implements a rigorous isolation layer. This layer ensures that every agent session runs in a hermetic environment, simulating a unique user context without polluting the host system or crossing tenant boundaries.

### **3.1 Tenant Configuration and Context Injection**

A **Test Tenant** is defined as a synthetic user entity with a specific persistent state and identity. The tenant.yaml configuration file defines the initial conditions for an agent execution.

**Tenant Configuration Parameters:**

* **Identity**: user\_id, username, groups. These are injected into the sandbox as environment variables (USER, HOME), allowing the agent to "login" and perceive itself as a specific user.17  
* **FileSystem State**: A specification of files that must exist before the agent starts. The platform uses a "hydration" process to populate the sandbox volume with these files (e.g., a dummy database.csv or a config.json).  
* **Resource Limits**: CPU and memory constraints applied to the container to prevent resource exhaustion during testing.

### **3.2 The Sandbox Interface**

The platform defines a Sandbox abstract base class that standardizes file system and shell interactions. This abstraction allows the underlying isolation mechanism to be swapped based on the deployment context (e.g., local development vs. production CI/CD).

**Table 2: Sandbox Implementation Comparison**

| Feature | LocalSandbox (Development) | DockerSandbox (Production/Eval) | SecureKernelSandbox (High Security) |
| :---- | :---- | :---- | :---- |
| **Isolation Mechanism** | Temporary Directory \+ Restricted Path Logic | Docker Container \+ Volume Mounts | gVisor / Kata Containers |
| **File System** | chroot simulation via Python pathlib | Logical container filesystem | Virtualized kernel filesystem |
| **Network Security** | Process-level firewall (difficult to enforce) | Docker Network constraints (easy to whitelist) | Kernel-level network namespaces |
| **Startup Latency** | Near zero (\< 10ms) | Low (500ms \- 2s) | Medium (1s \- 5s) |
| **Use Case** | Rapid local debugging of logic | CI/CD pipelines, Evaluation Suites | Running untrusted third-party agents |

#### **3.2.1 Implementing the Docker Sandbox**

The DockerSandbox is the primary implementation for the evaluation platform. When a test session begins, the ContextManager uses the Docker SDK to spin up an ephemeral container (e.g., based on python:3.10-slim).

* **Volume Mounting**: A unique temporary directory on the host is mounted to /workspace inside the container. This satisfies the "dedicated folder" requirement. The agent reads/writes to /workspace, and these changes are reflected in the host directory for post-execution analysis.  
* **User Simulation**: The container is started with the user flag corresponding to the synthetic user\_id defined in the tenant config. This ensures standard Linux permissions apply; the agent cannot modify files owned by root inside the container.  
* **Teardown**: Upon session completion (success or failure), the container is forcibly removed. The host directory can be preserved for debugging or deleted.3

### **3.3 Synthetic User Identity Management**

The requirement for "synthetic user id/login" is handled via Context Injection rather than complex authentication flows. Since the goal is evaluation, we trust the test runner to assert identity.

When the agent starts, the AgentRuntime initializes a UserContext object derived from the tenant config. This context populates a set of standardized environment variables within the sandbox:

* AGENT\_USER\_ID: The synthetic UUID.  
* AGENT\_HOME: The path to the dedicated folder.  
* AGENT\_SESSION\_TOKEN: A mock token if the agent needs to call external mock APIs.

This approach allows the agent to use tools that require identity (e.g., "get\_my\_profile") without needing an actual identity provider (IdP). The tools simply read the environment variables to determine *who* is asking.17

## ---

**4\. Observability and Trace Instrumentation**

To support the "call traces" evaluation requirement, the platform must produce high-fidelity logs of the agent's cognition and action. We adopt the **OpenTelemetry (OTEL)** Semantic Conventions for Generative AI 6, ensuring the trace data is structured, standardized, and compatible with external visualization tools like Jaeger or Arize Phoenix.

### **4.1 The Anatomy of an Agent Trace**

An agent execution is modeled as a hierarchical Trace.

1. **Root Span**: Represents the entire user interaction (e.g., run\_agent). Attributes include tenant.id, agent.id, and trace.id.  
2. **Child Spans**:  
   * **Reasoning Span**: Captures the raw LLM generation call. Attributes: gen\_ai.system, gen\_ai.request.model, gen\_ai.usage.input\_tokens.  
   * **Tool Execution Span**: Captures the specific tool invocation. Attributes: tool.name, tool.arguments (JSON), tool.result (text/JSON).  
   * **Observation Span**: Captures the system's feedback to the agent.

This structure is critical for the "assertion-based checklist." By querying the trace object, we can programmatically assert conditions like "The read\_file tool was called *after* list\_files" or "No tool call exceeded 5 seconds duration".6

### **4.2 Standardizing the Thought-Action Log**

The platform implements a TraceRecorder that subscribes to events in the AgentRuntime. As the agent loops through its ReAct cycle, the recorder builds a TraceObject.

**Trace Object Schema (JSON):**

JSON

{  
  "trace\_id": "tx-1234-5678",  
  "tenant\_id": "synth\_alice",  
  "steps":  
}

This standardized JSON is the payload delivered to the "LLM-as-a-Judge" evaluator. It allows the judge to "read" the agent's mind (thoughts) and verify its actions against its reasoning.21

## ---

**5\. The Evaluation Framework: LLM-as-a-Judge and Assertions**

The Evaluation Framework is the testing harness that subjects the agent (configured via agent.yaml) to the scenarios defined in tenant.yaml. It implements a dual-layer verification strategy: **Deterministic Assertions** for objective facts and **Probabilistic LLM Judging** for subjective quality.

### **5.1 Deterministic Evaluation: The Assertion Checklist**

For many aspects of agent performance, "correctness" is binary and measurable. The platform uses Python-based assertions to validate these. This satisfies the "assertion-based checklist" requirement.

#### **5.1.1 Filesystem State Assertions**

After the agent completes its run, the framework inspects the sandbox volume.

* **Existence Check**: Did the agent create the requested file?  
* **Content Integrity**: Does the file summary.txt contain the specific keyword "Revenue: $5M"?  
* **Side-Effect Safety**: Did the agent delete any files marked as "protected" in the tenant config?

#### **5.1.2 Trace Logic Assertions**

The framework iterates over the TraceObject to enforce behavioral rules.

* **Tool Hygiene**: Assert that tool.error count is 0\.  
* **Loop Efficiency**: Assert that the total number of steps is \< 10\.  
* **Syntax Compliance**: Assert that all JSON arguments generated by the LLM were valid according to the schema (no "Repair Loops" triggered).

### **5.2 Probabilistic Evaluation: LLM-as-a-Judge**

For requirements like "citation verification" and "reasoning quality," we cannot write simple code assertions. We employ a meta-evaluation strategy using a Judge LLM (typically a highly capable model like GPT-4o).

#### **5.2.1 Citation and Faithfulness Metric**

To verify citations (e.g., used in RAG workflows), the Judge evaluates the relationship between the **Retrieved Context**, the **Agent Response**, and the **Cited Source**.

**The Faithfulness Algorithm:**

1. **Extraction**: The framework parses the final response to extract statements and their associated citation markers (e.g., \[File A\]).  
2. **Verification**: For each citation, the framework retrieves the actual text of File A from the sandbox state.  
3. **Judgment**: The Judge LLM is prompted with the Statement and the Source Text. It answers: "Does the Source Text support the Statement?"  
   * If yes: Score \+1.  
   * If no (Hallucination): Score \-1.  
   * If the file does not exist (Broken Citation): Score \-5.

This rigorous check prevents the common agent failure mode of hallucinating sources or attributing facts to the wrong documents.23

#### **5.2.2 Trace Analysis via Prompt-Based Metrics**

To evaluate the "call traces," the Judge reviews the entire conversation history (Thoughts \+ Actions). This is driven by **Rubrics** defined in the test configuration.

**Example Rubric:** "Did the agent verify the file size before attempting to read it? Did it handle the 'File Not Found' error gracefully by searching alternative paths?"

The Judge reads the TraceObject JSON and outputs a score (1-5) along with a reasoning chain. This allows for qualitative assessment of the agent's *problem-solving strategy*, distinguishing between an agent that "got lucky" and one that reasoned correctly.25

### **5.3 Test Suite Orchestration**

The evaluation runner integrates these components into a unified workflow.

1. **Setup**: The runner parses the suite.yaml, identifying the agent config and the set of tenant configs (test cases).  
2. **Provision**: It spins up parallel Docker sandboxes for each tenant.  
3. **Execute**: It runs the agent against the user query in each sandbox, streaming traces to memory.  
4. **Evaluate**:  
   * It runs the **Assertion Checklist** against the final file system state and trace object.  
   * It dispatches the trace and response to the **Judge LLM** for grading.  
5. **Report**: It aggregates pass/fail rates, latency metrics, and Judge scores into a comprehensive HTML/JSON report.

## ---

**6\. Detailed Component Implementation Specifications**

This section provides the low-level data structures and logic flows required to implement the architecture described above.

### **6.1 Agent Runtime Implementation**

#### **6.1.1 The AgentRunner Class**

This is the main entry point for execution.

Python

class AgentRunner:  
    def \_\_init\_\_(self, agent\_config: AgentConfig, llm\_provider: LLMProvider, tool\_registry: ToolRegistry):  
        self.config \= agent\_config  
        self.llm \= llm\_provider  
        self.tools \= tool\_registry  
        self.memory \= MemoryBuffer(window\_size=config.model.context\_window)

    async def run(self, user\_query: str, sandbox: SandboxInterface) \-\> AgentResponse:  
        \# 1\. Initialize Context  
        self.memory.add(Message(role="system", content=self.config.instructions))  
        self.memory.add(Message(role="user", content=user\_query))

        \# 2\. Main ReAct Loop  
        steps \= 0  
        while steps \< self.config.flow.max\_turns:  
            \# Generate Thought/Action  
            response \= await self.llm.generate(self.memory.history, self.tools.schema)  
              
            if response.tool\_calls:  
                \# Execute Tools in Sandbox  
                for call in response.tool\_calls:  
                    result \= await self.\_execute\_tool(call, sandbox)  
                    self.memory.add\_tool\_result(call.id, result)  
            else:  
                \# Final Answer  
                return response.content  
              
            steps \+= 1  
          
        raise MaxTurnsExceededError()

#### **6.1.2 The DockerSandbox Implementation**

This class manages the lifecycle of the isolation environment.

Python

import docker

class DockerSandbox(SandboxInterface):  
    def \_\_init\_\_(self, tenant\_config: TenantConfig):  
        self.client \= docker.from\_env()  
        self.volume \= self.client.volumes.create(name=f"sandbox\_{tenant\_config.id}")  
        self.container \= None  
        self.\_hydrate\_volume(tenant\_config.files)

    def start(self):  
        self.container \= self.client.containers.run(  
            image="agent-runtime:latest",  
            volumes={self.volume.name: {'bind': '/workspace', 'mode': 'rw'}},  
            environment={"USER\_ID": self.tenant.user\_id},  
            detach=True,  
            network\_mode="none" \# Strong isolation  
        )

    def execute\_command(self, cmd: str) \-\> str:  
        exec\_result \= self.container.exec\_run(  
            cmd,   
            workdir="/workspace",   
            user=self.tenant.user\_id  
        )  
        return exec\_result.output.decode("utf-8")

This implementation satisfies the requirement for a "dedicated folder" (/workspace mapped to a named volume) and ensures that all CLI commands executed by the agent run inside the container context.3

### **6.2 Evaluation Framework Implementation**

#### **6.2.1 The Trace Object Schema**

To satisfy the "standard JSON schema for LLM agent execution traces" request, we define the following structure compatible with OpenTelemetry.

JSON

{  
  "trace\_id": "tr-550e8400-e29b",  
  "start\_time\_unix\_nano": 1698400000000000000,  
  "attributes": {  
    "agent.name": "DevOpsBot",  
    "agent.version": "1.0.0",  
    "tenant.id": "user\_123"  
  },  
  "spans":  
    }  
  \]  
}

This schema is consumed by the Judge LLM to evaluate the flow logic.6

#### **6.2.2 The Judge Prompt Template**

The core of the "LLM-as-a-Judge" system is the prompt engineering that converts the trace into a score.

You are an expert AI Quality Assurance Auditor.  
Your task is to evaluate the execution trace of an AI agent.  
CONTEXT:  
User Query: {{user\_query}}  
Tenant State: {{tenant\_file\_list}}  
TRACE:  
{{trace\_json}}  
EVALUATION CRITERIA (Rubric):

1. Did the agent verify file existence before reading?  
2. Did the agent use the 'grep' tool efficiently instead of reading whole files?  
3. Did the agent answer the user's specific question?

INSTRUCTIONS:

* Analyze the trace step-by-step.  
* Verify if the tool outputs justify the subsequent thoughts.  
* Assign a score from 1-5 (5 is best).  
* Output valid JSON.

OUTPUT SCHEMA:  
{  
"reasoning": "string",  
"score": int,  
"pass": bool  
}

### **6.3 Operational Best Practices**

#### **6.3.1 Dependency Management**

The platform itself manages dependencies via pyproject.toml. However, agents might need specific Python packages to run their tasks. The DockerSandbox image should be pre-baked with a standard data science environment (pandas, numpy, requests) to avoid runtime installation latency. For security, agents are prohibited from running pip install at runtime unless explicitly configured in the agent.yaml under a allow\_dynamic\_packages: true flag (not recommended for production).

#### **6.3.2 Handling Non-Determinism in Tests**

Since LLMs are non-deterministic, a single test run is statistically insignificant. The Evaluation Platform supports **Multi-Run Aggregation**. The config iterations: 5 instructs the runner to execute the same test case 5 times. The final report presents the "Pass Rate" (e.g., "80% Success") rather than a binary Pass/Fail. This is crucial for identifying "flaky" agents that usually work but occasionally fail due to probabilistic sampling.28

#### **6.3.3 Cost Control**

Running "LLM-as-a-Judge" (especially with GPT-4) is expensive. The platform implements a **Cascading Judge** strategy.

1. **Level 1**: Run Python Assertions (Free). If fail, stop.  
2. **Level 2**: Run Judge using a cheaper model (e.g., GPT-3.5-Turbo or local Llama 3\) for basic formatting checks.  
3. **Level 3**: Run Judge using SOTA model (GPT-4o) only for complex reasoning verification and citation checking.

## ---

**7\. Conclusion**

This specification defines a robust, enterprise-grade architecture for building and evaluating AI agents. By rigorously separating concerns—Model, Runtime, Environment, and Evaluation—the platform achieves the flexibility required by modern AI teams.

The system meets all key requirements:

* **Configurability**: Achieved via the agent.yaml schema and modular Tool Registry.  
* **End-to-End Execution**: Facilitated by the ReAct/DAG flow engine and LLMProvider abstraction.  
* **Sandboxing**: Enforced by the DockerSandbox implementation, ensuring secure "dedicated folder" operations.  
* **Trace & Citation Evaluation**: Delivered by the OpenTelemetry-compliant TraceRecorder and the "LLM-as-a-Judge" logic for faithfulness and logic auditing.  
* **Independence**: Guaranteed by the Adapter pattern, ensuring the platform is not vendor-locked to any specific LLM.

This architecture provides a stable foundation for the iterative development of reliable, autonomous agents, transforming the field from experimental scripting into a disciplined engineering practice.

#### **Works cited**

1. I built a Python script to compile natural language into commands for local LLMs. \- Reddit, accessed December 12, 2025, [https://www.reddit.com/r/Python/comments/1pie7b3/i\_built\_a\_python\_script\_to\_compile\_natural/](https://www.reddit.com/r/Python/comments/1pie7b3/i_built_a_python_script_to_compile_natural/)  
2. Pydantic AI, accessed December 12, 2025, [https://ai.pydantic.dev/](https://ai.pydantic.dev/)  
3. Unveiling ipybox: The Secure Code Sandbox Your AI Agent Needs \- Skywork.ai, accessed December 12, 2025, [https://skywork.ai/skypage/en/ipybox-secure-code-sandbox/1978663271827546112](https://skywork.ai/skypage/en/ipybox-secure-code-sandbox/1978663271827546112)  
4. All-in-One Sandbox for AI Agents that combines Browser, Shell, File, MCP and VSCode Server in a single Docker container. \- GitHub, accessed December 12, 2025, [https://github.com/agent-infra/sandbox](https://github.com/agent-infra/sandbox)  
5. AI Agent Evaluation | DeepEval \- The Open-Source LLM Evaluation Framework, accessed December 12, 2025, [https://deepeval.com/guides/guides-ai-agent-evaluation](https://deepeval.com/guides/guides-ai-agent-evaluation)  
6. Semantic Conventions for Generative AI Agentic Systems (gen\_ai.\*) · Issue \#2664 \- GitHub, accessed December 12, 2025, [https://github.com/open-telemetry/semantic-conventions/issues/2664](https://github.com/open-telemetry/semantic-conventions/issues/2664)  
7. Agent Spec: Unified Agent Workflow Definition \- Emergent Mind, accessed December 12, 2025, [https://www.emergentmind.com/topics/open-agent-specification-agent-spec](https://www.emergentmind.com/topics/open-agent-specification-agent-spec)  
8. any-agent: Mozilla's Python Library to Run AI Agents Anywhere, accessed December 12, 2025, [https://www.kodekx.com/blog/any-agent-mozillas-python-library-to-run-ai-agents-anywhere](https://www.kodekx.com/blog/any-agent-mozillas-python-library-to-run-ai-agents-anywhere)  
9. How can I build an LLM-based AI agent specialized on producing JSON documents with a certain schema? : r/LangChain \- Reddit, accessed December 12, 2025, [https://www.reddit.com/r/LangChain/comments/1iuaozq/how\_can\_i\_build\_an\_llmbased\_ai\_agent\_specialized/](https://www.reddit.com/r/LangChain/comments/1iuaozq/how_can_i_build_an_llmbased_ai_agent_specialized/)  
10. How JSON Schema Works for LLM Data \- Ghost, accessed December 12, 2025, [https://latitude-blog.ghost.io/blog/how-json-schema-works-for-llm-data/](https://latitude-blog.ghost.io/blog/how-json-schema-works-for-llm-data/)  
11. The Best Pre-Built Toolkits for AI Agents | by Amos Gyamfi | Medium, accessed December 12, 2025, [https://medium.com/@amosgyamfi/the-best-pre-built-toolkits-for-ai-agents-59652e4727fe](https://medium.com/@amosgyamfi/the-best-pre-built-toolkits-for-ai-agents-59652e4727fe)  
12. Workflows and agents \- Docs by LangChain, accessed December 12, 2025, [https://docs.langchain.com/oss/python/langgraph/workflows-agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)  
13. LangGraph \- LangChain, accessed December 12, 2025, [https://www.langchain.com/langgraph](https://www.langchain.com/langgraph)  
14. Multi-agent System Design Patterns From Scratch In Python | ReAct Agents \- Medium, accessed December 12, 2025, [https://medium.com/aimonks/multi-agent-system-design-patterns-from-scratch-in-python-react-agents-e4480d099f38](https://medium.com/aimonks/multi-agent-system-design-patterns-from-scratch-in-python-react-agents-e4480d099f38)  
15. Top 5 Open-Source Agentic Frameworks \- Research AIMultiple, accessed December 12, 2025, [https://research.aimultiple.com/agentic-frameworks/](https://research.aimultiple.com/agentic-frameworks/)  
16. Graph API overview \- Docs by LangChain, accessed December 12, 2025, [https://docs.langchain.com/oss/python/langgraph/graph-api](https://docs.langchain.com/oss/python/langgraph/graph-api)  
17. Synthetic Users: user research without the headaches, accessed December 12, 2025, [https://www.syntheticusers.com/](https://www.syntheticusers.com/)  
18. Sandboxing – Inspect, accessed December 12, 2025, [https://inspect.aisi.org.uk/sandboxing.html](https://inspect.aisi.org.uk/sandboxing.html)  
19. Semantic Conventions for GenAI agent and framework spans \- OpenTelemetry, accessed December 12, 2025, [https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)  
20. LLM Observability Terms and Concepts \- Datadog Docs, accessed December 12, 2025, [https://docs.datadoghq.com/llm\_observability/terms/](https://docs.datadoghq.com/llm_observability/terms/)  
21. AI Agent Evaluation Metrics | DeepEval \- The Open-Source LLM Evaluation Framework, accessed December 12, 2025, [https://deepeval.com/guides/guides-ai-agent-evaluation-metrics](https://deepeval.com/guides/guides-ai-agent-evaluation-metrics)  
22. What we think of the Opentelemetry semantic conventions for GenAI traces \- Portkey, accessed December 12, 2025, [https://portkey.ai/blog/opentelemetry-semantic-conventions-for-genai-traces/](https://portkey.ai/blog/opentelemetry-semantic-conventions-for-genai-traces/)  
23. DeepEval vs Ragas | DeepEval \- The Open-Source LLM Evaluation Framework, accessed December 12, 2025, [https://deepeval.com/blog/deepeval-vs-ragas](https://deepeval.com/blog/deepeval-vs-ragas)  
24. Ragas vs DeepEval: Measuring Faithfulness and Response Relevancy in RAG Evaluation, accessed December 12, 2025, [https://medium.com/@sjha979/ragas-vs-deepeval-measuring-faithfulness-and-response-relevancy-in-rag-evaluation-2b3a9984bc77](https://medium.com/@sjha979/ragas-vs-deepeval-measuring-faithfulness-and-response-relevancy-in-rag-evaluation-2b3a9984bc77)  
25. Using LLM-as-a-Judge to Evaluate Agent Outputs: A Comprehensive Tutorial \- Medium, accessed December 12, 2025, [https://medium.com/@juanc.olamendy/using-llm-as-a-judge-to-evaluate-agent-outputs-a-comprehensive-tutorial-00b6f1f356cc](https://medium.com/@juanc.olamendy/using-llm-as-a-judge-to-evaluate-agent-outputs-a-comprehensive-tutorial-00b6f1f356cc)  
26. Koyeb Sandboxes: Fast, Scalable, Fully Isolated Environments for AI Agents and More, accessed December 12, 2025, [https://www.koyeb.com/blog/koyeb-sandboxes-fast-scalable-fully-isolated-environments-for-ai-agents](https://www.koyeb.com/blog/koyeb-sandboxes-fast-scalable-fully-isolated-environments-for-ai-agents)  
27. Semantic conventions for Generative AI events \- OpenTelemetry, accessed December 12, 2025, [https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/)  
28. Unit Testing AI Agents: Common Challenges and Solutions \- Newline.co, accessed December 12, 2025, [https://www.newline.co/@zaoyang/unit-testing-ai-agents-common-challenges-and-solutions--0e337dd1](https://www.newline.co/@zaoyang/unit-testing-ai-agents-common-challenges-and-solutions--0e337dd1)