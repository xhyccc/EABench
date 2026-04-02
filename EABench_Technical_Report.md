# Technical Report: EABench - A Framework for Benchmarking Enterprise Agents

## Abstract

The transition from static software systems to probabilistic, agentic architectures represents a fundamental paradigm shift in enterprise application development. This report details the technical specification and implementation of **EABench**, a modular, LLM-agnostic platform designed to benchmark the *active execution* capabilities of AI agents. Unlike traditional benchmarks that focus on passive retrieval or static question answering, EABench evaluates an agent's ability to safely and correctly modify state within a secure enterprise environment. The system features a decoupling of reasoning and runtime, rigorous cryptographic sandboxing for execution, and a "trace-centric" evaluation methodology that audits the entire decision-making process, not just the final output.

## 1. Introduction

As organizations move beyond simple Retrieval-Augmented Generation (RAG) toward autonomous agents capable of multi-step reasoning, tool execution, and environment manipulation, the infrastructure supporting these systems must evolve. Current agent development is often fragmented and tightly coupled to specific model providers, rendering systems brittle and difficult to evaluate rigorously.

EABench addresses these challenges through:
1.  **Model Agnosticism**: Changing the reasoning engine without refactoring infrastructure.
2.  **Configuration-as-Code**: Defining agent behaviors and environments declaratively.
3.  **Sandboxed Execution**: Ensuring security through isolation (Docker/UserNS).
4.  **Observability-Driven Evaluation**: Assessing the validity of the execution trace using OpenTelemetry standards.

## 2. System Architecture

The architecture is built on the **Gateway-Adapter Pattern**, separating the core runtime from the underlying LLM provider.

### 2.1 The Agent Runtime
The Agent Runtime orchestrates the recursive loop of reasoning and acting. It hydrates an agent from a YAML configuration, manages its state (memory), and facilitates tool execution.

#### 2.1.1 Core Execution Loop (Pseudo-Code)
The core logic follows a standardized **ReAct (Reason + Act)** cycle. This loop is implemented in the `AgentRunner` class. It manages the conversation history, invokes the LLM, and handles the recursive execution of tools until a termination condition (final answer or max turns) is met.

```python
class AgentRunner:
    def __init__(self, config: AgentConfig, llm: LLMProvider, tools: ToolRegistry):
        self.config = config
        self.llm = llm
        self.tools = tools
        self.memory = MemoryBuffer(window=config.context_window)

    async def run(self, user_query: str) -> AgentResponse:
        # Initialize Context
        self.memory.add(Message(role="system", content=self.config.instructions))
        self.memory.add(Message(role="user", content=user_query))

        steps = 0
        while steps < self.config.max_turns:
            # 1. Generate Thought & Action
            # The LLM receives the full history + tool schemas
            response = await self.llm.generate(
                messages=self.memory.history,
                tools=self.tools.get_schemas()
            )
            
            # 2. Handle Tool Calls
            if response.tool_calls:
                for call in response.tool_calls:
                    # Execute tool in isolated environment
                    result = await self.tools.execute(call.name, call.args)
                    self.memory.add_tool_result(call.id, result)
            else:
                # 3. Terminal State (Final Answer)
                return response.content
            
            steps += 1
          
        raise MaxTurnsExceededError("Agent failed to converge.")
```

-   **Declarative Configuration**: Agents are defined in `agent.yaml`, separating logic from code. The schema includes sections for `Meta` (versioning), `Model` (provider settings), `Context` (prompts), and `Tools` (capabilities).
-   **LLM Abstraction Layer**: An `LLMProvider` interface normalizes inputs/outputs. Adapters (e.g., `OpenAIAdapter`, `AnthropicAdapter`) handle provider-specific API quirks. This includes an **Output Parser** that repairs malformed tool calls from less capable models.

### 2.2 Tool Registry & Execution
Tools are Python functions decorated with `@tool`, utilizing Pydantic models to automatically generate JSON Schemas for the LLM. High-risk tools (like `cli_run`) proxy commands into the Sandbox environment rather than executing on the host.

#### 2.2.1 The Decorator Pattern & Schema Generation
The registry uses introspection to convert Python type hints into Open API Specification (OAS) schemas required by LLMs. This ensures that the documentation seen by the model always matches the actual code implementation, preventing "schema drift."

```python
# Technical Implementation of the Tool Definition
from pydantic import BaseModel, Field

class FileInput(BaseModel):
    path: str = Field(..., description="Absolute path to the file.")
    encoding: str = Field("utf-8", description="File encoding.")

@tool(name="read_file", args_schema=FileInput)
def read_file(path: str, encoding: str = "utf-8") -> str:
    """Reads content from the sandboxed filesystem."""
    # Validation occurs automatically via Pydantic before execution enters here
    validate_path_is_safe(path) 
    return _fs.read(path, encoding)
```

## 3. Data Generation Pipeline

To ensure ecological validity, EABench avoids static datasets in favor of procedural generation.

### 3.1 Tenant Generation: The Enterprise Knowledge Graph
The `generate_data.py` pipeline does not merely create isolated files; it constructs a coherent **Enterprise Knowledge Graph** that models the complex interdependencies of a real organization. This graph serves as the "ground truth" for deep research tasks.

#### 3.1.1 Supported Data Modalities
The generator produces a diverse array of unstructured and semi-structured data types, mimicking the noise and variety of modern work:

*   **People Information**: Rich profiles including hierarchical roles (Org Chart), departmental affiliation, skills, and historical project involvement.
*   **Asynchronous Communication**:
    *   **Email Corpora**: Threaded SMTP-style messages with multi-recipient targeting (To/Cc/Bcc), timestamps, and attachments.
    *   **Discussion Channels**: Persistent, topic-based chat logs (resembling Slack/Teams) depicting high-velocity, informal collaboration.
    *   **Direct Messages (Group Chat)**: Private, ephemeral conversations between subsets of users.
*   **Files & Knowledge Artifacts**:
    *   **Documents**: PDFs (policy docs), DOCX (proposals), and TXT notes.
    *   **Structured Data**: CSV/XLSX spreadsheets (financials, employee rosters).
    *   **Code**: Python/JSON/YAML repositories for technical scenarios.
*   **Events**:
    *   **Calendar Entries**: Meeting metadata (Time, Location, Invitees).
    *   **Meeting Transcripts**: Verbatim, speaker-diarized logs of voice conversations, linking back to the calendar event.

#### 3.1.2 Graph Topology and Connectivity
To benchmark "Deep Research," the agent must navigate the edges of this graph. The generation engine adheres to a strict schema of relationships:

1.  **Organizational Hierarchy ($U \rightarrow U$)**:
    The graph starts with a directed acyclic graph (DAG) representing the Org Chart. This influences information flow—managers have access to different scope than individual contributors.

2.  **Communication Graph ($U \xrightarrow{sent} M \xrightarrow{received} U$)**:
    Every email or chat message represents a directed edge between nodes. The generator respects probability distributions for interaction frequency based on "Social Distance" in the org chart (e.g., frequent intra-team chat, sparse inter-departmental email).

3.  **Event-Artifact Bridge ($E \xrightarrow{has} T \xrightarrow{mentions} D$)**:
    Meetings ($E$) are central hubs. They have Attendees ($U$), produce Transcripts ($T$), and referenced Documents ($D$).
    *   *Scenario Example*: A meeting about "Q3 Budget" will link to `finance_q3.xlsx`. The transcript will contain dialogue where User A mentions the file explicitly.

4.  **Temporal Consistency**:
    All edges are timestamped. A file attached to an email must have a creation date *before* the email was sent. This allows for temporal reasoning tasks (e.g., "Find the version of the proposal sent *before* the Friday meeting").

#### 3.1.3 Complexity Mechanisms for Deep Research
The true difficulty of Enterprise Deep Research lies not in finding a single keyword, but in traversing **Multi-Hop Dependency Chains** across these graph nodes. The synthetic graph introduces specific complications to stress-test agent reasoning:

*   **Information Fragmentation (The "Jigsaw" Problem)**:
    Crucial data is rarely in one place.
    *   *Example*: The *existence* of a project is mentioned in an **All-Hands Email**. The *Project Lead's name* is only found in a **Slack Channel**. The *Link to the specifications* is in the Project Lead's **personal notes**.
    *   *Challenge*: The agent must follow the chain: `Email` $\rightarrow$ `Topic Search` $\rightarrow$ `Slack` $\rightarrow$ `Identify Person` $\rightarrow$ `Person's Files`.

*   **Version Conflict & Temporal Resolution**:
    The graph introduces conflicting nodes to test temporal groundedness.
    *   *Example*: `Q3_Report_v1.pdf` is sent on Tuesday. A meeting occurs Wednesday where changes are discussed. `Q3_Report_Final.pdf` is uploaded Thursday.
    *   *Challenge*: If the user asks "What was the budget *during* the Wednesday meeting?", the agent must retrieve `v1`, not `Final`, despite `Final` being the "better" document.

*   **Ambiguity & Entity Resolution**:
    The generator introduces purposely ambiguous entities.
    *   *Example*: Two users named "Michael". A file named `budget.xlsx` exists in both Marketing and Engineering folders.
    *   *Challenge*: The agent must use context from the query (e.g., "Michael from Engineering") or inferred social distance to disambiguate the correct node.

#### 3.1.4 Chain-of-Thought Data Synthesis Prompts
To maintain narrative coherence across thousands of generated files, we employ a hierarchical Chain-of-Thought (CoT) prompting strategy. This "Casdcade of Context" ensures that a file generated on Day 5 is causally linked to an email sent on Day 3.

**Phase 1: Company Profile & Backbone Narrative**
```text
SYSTEM: You are a creative director for a simulation.
PROMPT: Generate a comprehensive profile for a fictional Tech Company. 
Include:
1. Core Products & Business Model
2. Current Market Challenges (e.g., "Impending lawsuit", "Product Delay")
3. Key Departments and their Heads (Personas)
OUTPUT: { "company_name": "NexusAI", "crisis": "Data Leak Scrutiny", ... }
```

**Phase 2: Project Storyline & Daily Trajectory**
```text
PROMPT: Given the company context 'NexusAI' and crisis 'Data Leak', generate a 14-day 'Topic Trajectory'.
For each day, define the primary focus/event.
Day 1: Discovery of leak.
Day 2: Emergency executive meeting.
...
Day 14: Public press release.
```

**Phase 3: Daily Grounding Data Instantiation**
```text
PROMPT: Focusing on Day 2 (Emergency Meeting), generate the specific artifacts:
1. An urgent EMAIL from the CTO to the Legal Counsel (Subject: "Immediate Sync").
2. A CALENDAR INVITE for "War Room" (Attendees: C-Suite).
3. A TRANSCRIPT of the meeting discussion where they mention "Logs_v2.txt".
Ensure the tone matches the 'High Stress' attribute of the personas.
```

### 3.2 Evaluation Query Set Generation

The `generate_eval.py` tool produces `eval_dataset_<timestamp>.yaml`. Unlike typical QA datasets which focus on fact retrieval, our query generation engine classifies tasks into two complexity tiers to specifically test agentic behaviors.

#### 3.2.1 Generation Methodology: Topic-Driven Scenario Synthesis
To ensure queries are semantically meaningful and rooted in realistic work patterns, we do not randomly sample files. Instead, we employ a 4-step **Scenario-First** generation pipeline:

1.  **Semantic Topic Grouping**:
    The engine scans the generated Enterprise Knowledge Graph and clusters grounding data points (emails, files, meetings, chats) based on their latent topics (e.g., "Project Apollo", "Q3 Budgeting", "Office Renovation"). This ensures that the data points selected for a query are contextually related.

2.  **Contextual Batch Sampling**:
    From a single topic cluster, the system selects a small, coherent batch of data.
    *   *Example*: It selects an Email thread about "Budget Cuts", the attached `financials.xlsx`, and a Transcript from the "Finance All-Hands" meeting.

3.  **Scenario Hallucination**:
    An LLM (acting as the Data Generator) analyzes this selected batch to "make sense" of it. It imagines a plausible **Work Scenario** that would require a user to access this specific combination of information.
    *   *Goal*: Construct a user intent (e.g., "The user is preparing a summary for the CFO") rather than a mechanical search task.

4.  **CoT Query & Assertion Generation**:
    Using Chain-of-Thought (CoT), the Generator formulates the final test case:
    *   **The Query**: Formulated as either Type A (Search) or Type B (Multi-hop), targeting the selected batch.
    *   **Target Grounding Data**: Explicitly labeling which files/emails from the batch *must* be retrieved.
    *   **Golden Assertions**: Defining *how* the information should be represented in the answer (e.g., "Must cite the deficit figure from the Excel file").

#### 3.2.2 Query Generation Implementation (Pseudo-Code)
The following pseudo-code illustrates the programmatic flow of the scenario synthesis engine, highlighting the use of embeddings for clustering and the LLM for creative hallucination.

```python
# Pseudo-code for Topic-Driven Query Generation
def generate_eval_case(knowledge_graph: Graph, generator_llm: LLM) -> TestCase:
    # Step 1: Semantic Topic Grouping
    # Cluster heterogeneous nodes (Emails, Files, Meetings) by latent embedding similarity
    # This prevents random sampling of unrelated files.
    clusters = cluster_nodes_by_embedding(knowledge_graph.get_all_nodes())
    
    # Step 2: Contextual Batch Sampling
    # Select a cluster with high internal connectivity (e.g., "Project Apollo Launch")
    target_cluster = select_richest_cluster(clusters)
    
    # Sample a connected subgraph (e.g., 1 Meeting + 2 Emails + 1 File)
    batch_context = target_cluster.sample_connected_subgraph(size=5) 
    
    # Step 3 & 4: Scenario Hallucination and CoT Formulation
    # The Generator LLM acts as a "Scenario Writer"
    prompt = f"""
    Available Context Data:
    {batch_context.serialize()}
    
    Task:
    1. Analyze the relationships between these documents.
    2. Imagine a realistic enterprise work scenario (e.g., Audit, Onboarding) requiring this data.
    3. Formulate a 'Multi-Hop' search query that forces the user to traverse the link from {batch_context.root} to {batch_context.leaf}.
    4. Define 3-5 'Golden Assertions' that specifically check if the final answer is grounded in the file content.
    
    Output Format (JSON): {{ "scenario_description": str, "query": str, "assertions": List[Dict] }}
    """
    
    output = generator_llm.generate(prompt)
    
    return TestCase(
        id=generate_uuid(),
        query=output.query,
        assertions=output.assertions,
        ground_truth_nodes=batch_context.node_ids
    )
```

#### 3.2.3 Type A: Single-Target Contextual Search (Constraint Satisfaction)
These queries target a specific node in the graph (People, Email, Chat, File, Group Chat, Meeting) but describe it through **Context and Constraints** rather than unique identifiers (like IDs or exact filenames). The agent must formulate filters to resolve the description to a single, unique entity.

*   **Structure**: `[Action] [Target Type] where [Constraint 1] AND [Constraint 2] ...`
*   **Target Types**:
    *   **People**: Role-based or history-based lookup.
        *   *Example*: "Find the contact info for the *Product Manager* who ran the *Mobile App Launch* project."
    *   **Email**: Sender, Recipient, Time, and Topic filtering.
        *   *Example*: "Forward the email from *Alice* received *last week* regarding 'Budget Cuts' to Bob."
    *   **Meeting**: Organizer, Attendees, Date, and Topic.
        *   *Example*: "Summarize the *Marketing Sync* meeting that *David* attended on *Tuesday*."
    *   **File**: Content, Author, Creation Date, Location.
        *   *Example*: "Locate the *Excel spreadsheet* created in the */finance* folder *after Q2 started*."

#### 3.2.4 Type B: Multi-Hop Dependent Reasoning (Chain-of-Execution)
These queries require the agent to traverse multiple nodes $[N_1, N_2, ..., N_k]$ in sequence. Crucially, the search parameters for hop $N_{i+1}$ are **unknown** until the result of hop $N_i$ is retrieved and analyzed. This tests **Dependent Search** capabilities—the agent cannot simply parallelize searches; it must reason about intermediate state.

*   **Structure**: `Find [Artifact Y] associated with [Entity X], where [Entity X] is defined by [Constraint Z].`
*   **Workflow Example**: "Find the *financial report* attached to the email sent by the *person who led the Q3 Architecture Review meeting*."
    1.  **Hop 1 (Meeting Search)**: Find "Q3 Architecture Review". Parse attendees/organizer. $\rightarrow$ Identify *Sarah*.
    2.  **Hop 2 (Email Search)**: Construct query `sender: Sarah` + `has_attachment: True` + `topic: financial`. $\rightarrow$ Identify *Email #502*.
    3.  **Hop 3 (File Access)**: Download attachment `report_final.pdf` from *Email #502*.
*   **Graph Traversal**: This forces the agent to navigate edges: $Meeting \xrightarrow{organized\_by} Person \xrightarrow{sent} Email \xrightarrow{has} File$.

The dataset generation records the **Ground Truth Path** (the sequence of correct node IDs), allowing the evaluator to verify not just the final file, but whether the agent took the correct logical path through the graph.

#### 3.2.5 Query Synthesis Prompts
To generate these complex queries, the system uses template-based prompting that enforces the distinction between single target and multi-hop structures.

**Template A: Single Target Contextual Search**
```text
PROMPT: Given the artifacts: [Email_101 ("Project Delay"), File_202 ("Updated Roadmap")].
Goal: Create a Natural Language query that uniquely identifies 'File_202' WITHOUT using its name.
Constraint: Reference the file by its *relationship* to Email_101 or its content.
Example Output: "Find the roadmap document that was attached to the email regarding the delay."
```

**Template B: Multi-Hop Reasoning Chain**
```text
PROMPT: Given the chain: User_A -> Meeting_B -> File_C.
Goal: Create a multi-step query.
Step 1: The user knows about User_A.
Step 2: User_A organized Meeting_B (hidden variable).
Step 3: File_C was presented at Meeting_B (target).
Instruction: Ask for File_C by referencing User_A's meeting.
Example Output: "Find the presentation deck from the meeting organized by User_A last Friday."
```

## 4. Evaluation Framework

EABench employs a dual-layer evaluation strategy: **Deterministic Assertions** for objective facts and **probabilistic "LLM-as-a-Judge"** for subjective quality.

### 4.1 Trace-Centric Auditing
We adopt OpenTelemetry (OTEL) Semantic Conventions for Generative AI. An execution **Trace** captures the full causal graph of the agent's behavior.

#### 4.1.1 Trace Data Structure
The platform serializes the execution log into a standardized JSON format that serves as the input for "Process-Oriented Auditing."

```json
{
  "trace_id": "tx-1234-5678",
  "start_time": "2023-10-27T10:00:00Z",
  "steps": [
    {
      "step_id": 1,
      "type": "thought",
      "content": "I need to find the sales report first."
    },
    {
      "step_id": 2,
      "type": "tool_call",
      "tool_name": "list_files",
      "arguments": { "path": "." }
    },
    {
      "step_id": 3,
      "type": "observation",
      "content": "['sales_Q3.pdf', 'emails/']"
    }
  ],
  "outcome": "success"
}
```

This structure allows evaluators to write logic assertions against the *history*, e.g., `assert "list_files" in trace.tool_calls`, ensuring the process is robust, not just lucky.

1.  **Reasoning Span**: The raw thought process.
2.  **Tool Execution Span**: Arguments, execution time, and stdout/stderr.
3.  **Observation Span**: System feedback.

### 4.2 LLM-as-a-Judge
A "Judge" LLM (e.g., GPT-4o) evaluates subjective metrics based on the Trace Object. This process converts qualitative behaviors into quantitative scores (1-5 Likert scale) or boolean checks.

#### 4.2.1 Faithfulness Verification Algorithm
One of the most critical metrics for enterprise agents is "Faithfulness"—ensuring the agent does not hallucinate facts not present in the retrieved context. The framework extracts assertions from the agent's final answer and cross-references them against the files accessed during the trace.

```python
# Pseudo-code for Citation & Faithfulness Logic
async def evaluate_faithfulness(trace: ExecutionTrace, final_answer: str) -> float:
    # 1. Extract Citation Markers (e.g., "[File A]")
    claims = extract_claims(final_answer) 
    
    score = 0
    for claim in claims:
        # 2. Retrieve Ground Truth
        # Fetch the actual content of the file the agent *claimed* to read
        source_doc = trace.get_tool_output(tool="read_file", path=claim.source_id)
        
        # 3. Judge Validation
        # Ask the Judge: "Does the source text support the statement?"
        verdict = await judge_llm.verify(
            statement=claim.text,
            context=source_doc
        )
        
        if verdict.is_supported:
            score += 1
        elif verdict.is_contradicted:
            score -= 1  # Hallucination Penalty
        else:
            score -= 5  # Broken Citation / 'Not Found' Penalty
            
    return normalize(score)
```

### 4.3 Response Quality Metrics

We implement a multi-dimensional framework to evaluate answer quality, moving beyond simple similarity metrics.

#### 4.3.1 Relevance-Based Citation Scoring (NDCG@K)
Standard RAG evaluation checks for citation presence but ignores *rank quality*. We treat the agent's citation list as a ranked retrieval result and compute **Normalized Discounted Cumulative Gain (NDCG)**.

**Algorithm Design:**
1.  **Extraction**: Parse citations $[c_1, c_2, ..., c_k]$ from the agent's response.
2.  **Scoring**: The Judge LLM rates the relevance ($rel_i$) of each cited document to the user query on a scale of 0-3 (Irrelevant, Partially Relevant, Relevant, Highly Relevant).
3.  **Calculation**: Compute DCG and normalize against an Ideal DCG (IDCG) derived from the ground truth relevance set.

```python
def calculate_citation_ndcg(query: str, citations: List[Document], judge: LLM) -> float:
    relevance_scores = []
    
    # Pointwise Relevance Scoring by Judge
    for doc in citations:
        score = judge.predict(
            prompt=f"Rate relevance of {doc.content} to {query} on scale 0-3."
        )
        relevance_scores.append(int(score))
    
    # Calculate DCG: sum(rel_i / log2(i+1 + 1))
    dcg = sum(
        (2**rel - 1) / math.log2(idx + 2) 
        for idx, rel in enumerate(relevance_scores)
    )
    
    # Normalize by IDCG (Ideal ordering)
    idcg = calculate_idcg(sorted(relevance_scores, reverse=True))
    return dcg / idcg if idcg > 0 else 0.0
```

#### 4.3.2 LLM Checklist (Assertion-Based Auditing)
To tackle the "vagueness" of general quality scores, we employ a checklist of **Golden Assertions**. These are fact-specific boolean checks generated automatically alongside the synthetic data.

**Design & Data Flow:**
*   **Generation Phase**: When `generate_eval.py` creates a scenario (e.g., "HR Audit"), it knows the ground truth (e.g., "Alice's salary is $150k"). It appends an assertion: `{"check": "contains value '$150k'", "target": "Alice's salary"}`.
*   **Evaluation Phase**: The Judge LLM receives specific instructions to verify ONLY these facts, reducing cognitive load and hallucination in the grading process.

```python
class AssertionResult(BaseModel):
    passed: bool
    reasoning: str

async def check_golden_assertions(response: str, checklist: List[str]) -> float:
    results = []
    for assertion in checklist:
        # Targeted entailment check
        result = await judge_llm.evaluate(
            instruction=f"Does the response satisfy this condition: {assertion}?",
            response=response
        )
        results.append(result.passed)
    
    return sum(results) / len(results) # Pass Rate
```

#### 4.3.3 Side-by-Side (SxS) Pairwise Comparison
For qualitative assessment (tone, formatting, conciseness), absolute scoring (1-5) is often calibrated poorly. We implement a **Pairwise Preference Model** (Bradley-Terry) to compare a Control agent ($A$) against a Treatment agent ($B$).

**Architectural Consideration: Positional Bias**
LLMs often prefer the first option presented. Our framework mitigates this via **Swap-and-Average**:
1.  Run `Compare(A, B)` → Result 1
2.  Run `Compare(B, A)` → Result 2
3.  Verdict is valid only if consistent or if the "Tie" confidence is high.

```python
async def sxs_compare(query: str, trace_a: Trace, trace_b: Trace) -> Winner:
    # Construct "Glass Box" comparison prompt containing trace details
    prompt = f"""
    Query: {query}
    
    Model A Execution:
    - Steps: {len(trace_a.steps)}
    - Final Answer: {trace_a.response}
    
    Model B Execution:
    - Steps: {len(trace_b.steps)}
    - Final Answer: {trace_b.response}
    
    Which model followed a more efficient path and provided a better answer?
    """
    
    verdict = await judge_llm.predict(prompt)
    return verdict.winner # 'A', 'B', or 'Tie'
```

### 4.4 Prompt Registry for Evaluation Judges
To ensure reproducibility, the exact prompts used by the Judge LLMs are version-controlled.

**Metric 1: Citation Relevance (NDCG Calculation)**
```text
SYSTEM: You are an impartial search quality rater.
INPUT: 
Query: "{user_query}"
Document Content: "{cited_document_snippet}"
TASK: Rate the relevance of the document to the query on a specific scale.
SCALE:
0 - Irrelevant: No useful information.
1 - Partially Relevant: Tangential mentions.
2 - Relevant: Contains part of the answer.
3 - Highly Relevant: Contains the direct answer or is the primary source.
OUTPUT: Integer 0-3 ONLY.
```

**Metric 2: Side-by-Side (SxS) Comparison**
```text
SYSTEM: You are a judge evaluating two AI assistants.
INPUT: 
User Request: "{user_query}"
Model A Trace: {model_a_steps}
Model A Answer: "{model_a_final}"
Model B Trace: {model_b_steps}
Model B Answer: "{model_b_final}"
TASK: Compare based on 1. Accuracy 2. Efficiency (fewer steps) 3. Safety.
OUTPUT: { "winner": "Model A" | "Model B" | "Tie", "reasoning": "..." }
```

**Metric 3: LLM Assertion Checklist**
```text
SYSTEM: You are a fact-checking auditor.
INPUT:
Agent Response: "{agent_response}"
Golden Assertion: "{assertion_text}" (e.g., "Must contain value $15M")
TASK: Determine if the specific assertion is chemically present (entailed) in the response.
OUTPUT: { "passed": true/false }
```

## 5. A/B Testing and Differential Scorecards

A core feature of EABench is the ability to statistically compare two agent configurations (e.g., `v1` vs `v2`).

### 5.1 Methodology
The system runs both agents against the same set of Tenant Scenarios. We calculate the Delta ($\Delta$) for Key Performance Indicators (KPIs):
-   **Success Rate**: Absolute difference in pass rates.
-   **Efficiency**: Difference in token usage and steps taken.
-   **Latency**: End-to-end execution time.

### 5.2 Statistical Significance (P-Value)
To distinguish genuine improvements from random variance (common in probabilistic models), EABench calculates **P-Values** for these metrics. The Web UI (`app.py`) renders a **Unified Scorecard Table** displaying:

| Metric | Control | Treatment | Diff ($\Delta$) | P-Value |
| :--- | :--- | :--- | :--- | :--- |
| **Success Rate** | 82% | 89% | **+7%** | $0.042^*$ |
| **Avg Steps** | 12.4 | 8.1 | **-4.3** | $< 0.001^{***}$ |

This rigorous statistical approach prevents "blind upgrades" and quantifies the trade-off between cost, speed, and accuracy.

## 6. Visualization & User Interface

The platform provides a Streamlit-based dashboard (`app.py`) for real-time interaction and analysis:
-   **Chat Mode**: Interactive debugging with "glass-box" visibility into thoughts and tool outputs.
-   **Evaluation Mode**: Running batch test suites and viewing aggregated reports.
-   **Side-by-Side Comparison**: Visualizing traces of two agents efficiently to identify where their behavior diverged.

## 7. Comparative Analysis

EABench differentiates itself from existing benchmarks like **DRBench** (ServiceNow) and **HERB** (Salesforce):

| Feature | DRBench | HERB | **EABench** |
| :--- | :--- | :--- | :--- |
| **Primary Focus** | Passive Research | RAG Retrieval | **Active Execution & State Modification** |
| ** Capabilities** | Read-Only | Read-Only | **Read/Execute (Full Environment Interaction)** |
| **Environment** | Docker Task-Loader | Static Dataset | **Sandboxed Tenants (Docker/UserNS)** |
| **Evaluation** | Insight Recall | RAG Metrics | **Process Tracing (OTEL) + State Assertions** |
| **Data Strategy** | Fixed Tasks | Static | **Procedural Generation (Infinite Scenarios)** |

## 8. Conclusion

EABench provides a stable, enterprise-grade foundation for the iterative development of autonomous agents. By rigorously separating concerns—Reasoning, Runtime, Environment, and Evaluation—and applying statistical rigor to performance metrics, it transforms agent development from experimental scripting into a disciplined engineering practice.
