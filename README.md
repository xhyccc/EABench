# EABench - Agent Execution and Evaluation Platform

EABench is a modular platform designed to execute and evaluate LLM agents in a sandboxed environment. It simulates a realistic enterprise setting with office automation data (emails, chats, meetings, files) and provides tools for agents to interact with this data securely.

## Features

- **Sandboxed Execution**: Agents run in a controlled environment with restricted access.
- **Multi-Provider Support**: Supports Azure OpenAI and OpenAI-compatible providers (e.g., SiliconFlow).
- **Flexible Embeddings**: Choose between Azure OpenAI Embeddings or high-quality Local Embeddings (using `sentence-transformers`) for semantic search.
- **Vector Search Engine**: Built-in semantic search for retrieving relevant context from tenant data.
- **Role-Based Access Control**: Search results are filtered based on the logged-in user's permissions (e.g., users can only search emails they sent or received).
- **Data Analysis Capabilities**: The agent can execute Python code to analyze data using libraries like `pandas`, `scikit-learn`, `matplotlib`, and `networkx`.
- **Rich Test Dataset**: Includes a "Project Alpha" story arc with realistic team interactions, crises, and resolutions.
- **Web Interface**: A Streamlit-based UI for interactive testing and demonstration.

## Prerequisites

- Python 3.10 or higher
- An Azure OpenAI API key OR an OpenAI-compatible API key (e.g., SiliconFlow)
- (Optional) For local embeddings: Sufficient RAM to run `all-MiniLM-L6-v2` (approx. 1GB).

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd EABench
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   # Note: This installs sentence-transformers, pandas, scikit-learn, etc.
   ```

## Configuration

1. **Environment Variables:**
   Create a `.env` file in the root directory based on your provider.

   **For Azure OpenAI:**
   ```env
   AZURE_API_KEY=your_azure_api_key
   AZURE_ENDPOINT=https://your-resource.openai.azure.com/
   AZURE_API_VERSION=2024-12-01-preview
   # Optional if using local embeddings
   AZURE_EMB_API_VERSION=2023-05-15
   ```

   **For OpenAI / SiliconFlow:**
   ```bash
   # .env
   OPENAI_API_KEY=your_api_key
   OPENAI_API_BASE=https://api.siliconflow.cn/v1
   ```

2. **Agent Configuration (`examples/agent.yaml`):**
   You can configure the LLM and Embedding provider separately.

   **Example with Azure LLM and Local Embeddings:**
   ```yaml
   model:
     provider: azure
     name: gpt-4o
     parameters:
       temperature: 0.7
   
   embedding:
     provider: local
     model: all-MiniLM-L6-v2
   ```

   **Example with Azure LLM and Azure Embeddings:**
   ```yaml
   embedding:
     provider: azure
     model: text-embedding-ada-002
   ```

3. **Tenant Config:**
   - Tenant data and configuration are in `examples/tenants/test-tenant-1/`.

## Usage

### 1. Web UI (Recommended)
The Web UI allows you to log in as different users and interact with the agent from their perspective.

```bash
python -m streamlit run app.py
```
- Open your browser at `http://localhost:8501`.
- Select a user from the sidebar (e.g., `user123`, `user456`).
- Ask questions like:
  - *"What is the status of Project Alpha?"*
  - *"Find emails about the memory leak."*
  - *"Summarize the last team meeting."*

### 2. CLI Mode
You can also run the agent directly from the command line.

```bash
python main.py
```
This will index the data and run a hardcoded query defined in `main.py`.

## Project Structure

- `src/core/`: Core logic for Agent Runner, LLM Providers, and Search Engine.
- `src/config/`: Configuration schemas (Pydantic models).
- `src/sandbox/`: Sandbox implementation for file system operations.
- `examples/tenants/`: Test data (YAML files for users, emails, chats, etc.).
- `app.py`: Streamlit Web Application.
- `main.py`: CLI Entry point.

## Test Data: Project Alpha
The default tenant (`test-tenant-1`) is populated with a story about "Project Alpha":
- **Scenario**: A software team rushing to launch a product named "SmartInsights".
- **Key Events**: A critical memory leak discovered days before launch, emergency meetings, and a successful resolution.
- **Characters**:
  - `user123` (Test User): Developer
  - `user456` (Big Boss): Manager
  - `user789` (Peer Dev): Developer
