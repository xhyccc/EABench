# **Addendum: Domain-Specific Search Strategy Proposal**

## **1. Overview**

This proposal outlines a unified "Query Understanding" architecture for all search domains (Files, Chats, Meetings, People), mirroring the successful implementation in the Email domain. The core philosophy is to **analyze intent before execution**, allowing the system to choose the most efficient retrieval strategy (Exact Match, Semantic Search, Filtering, or Hybrid) rather than relying solely on vector similarity.

## **2. The "Query Understanding" Pattern**

For every domain-specific search tool, the execution flow will be:

1.  **Input**: User natural language query.
2.  **Analysis (LLM)**: A lightweight LLM call analyzes the query to extract:
    *   **Strategy**: The best retrieval method (e.g., `recent`, `semantic`, `filter`).
    *   **Parameters**: Structured filters (e.g., `author`, `date_range`, `file_type`).
    *   **Refined Query**: A keyword-optimized version of the query for vector search.
3.  **Execution**: The tool executes the logic corresponding to the selected strategy.
4.  **Output**: A curated list of results.

---

## **3. Domain Specifications**

### **3.1 Domain: Files (`search_file`)**

**Objective**: Retrieve documents based on content, metadata, or recency.

**Proposed Strategies:**
*   **`filename_exact`**: User asks for a specific file by name (e.g., "Open budget.xlsx").
    *   *Action*: Exact string match on file paths.
*   **`semantic`**: User asks about content concepts (e.g., "project plan for Q3").
    *   *Action*: Vector search on `file_contents` index.
*   **`author_filter`**: User asks for files by a specific person (e.g., "Files created by Alice").
    *   *Action*: Filter `files_metadata` by `created_by` field.
*   **`type_filter`**: User asks for specific formats (e.g., "Show me all PDFs").
    *   *Action*: Filter by file extension.
*   **`recent`**: User asks for latest work (e.g., "What files were added today?").
    *   *Action*: Sort `files_metadata` by `last_modified` descending.

**LLM Analyzer Prompt:**
> "Analyze the file search query. Extract `strategy` (filename_exact, semantic, author_filter, type_filter, recent), `filename`, `author`, `file_type`, and `refined_query`."

---

### **3.2 Domain: Chats & Channels (`search_chat`, `search_channel`)**

**Objective**: Retrieve conversational context from 1:1 chats, group chats, or public channels.

**Proposed Strategies:**
*   **`participant_filter`**: User asks about a specific person's messages (e.g., "What did Bob say about the bug?").
    *   *Action*: Filter messages where `from_user` matches target, then apply semantic search.
*   **`date_range`**: User asks about a specific time (e.g., "Messages from yesterday").
    *   *Action*: Filter by `timestamp`.
*   **`semantic`**: General topic search (e.g., "discussions about deployment").
    *   *Action*: Vector search on `chats` / `channels` index.
*   **`recent`**: Context retrieval (e.g., "Catch me up on the last 10 messages").
    *   *Action*: Fetch last N messages sorted by time.

**LLM Analyzer Prompt:**
> "Analyze the chat search query. Extract `strategy` (participant_filter, date_range, semantic, recent), `participant_name`, `time_period`, and `refined_query`."

---

### **3.3 Domain: Meetings (`search_meeting`)**

**Objective**: Retrieve meeting details, agendas, or specific spoken quotes from transcripts.

**Proposed Strategies:**
*   **`transcript_search`**: User asks about what was *said* (e.g., "Did we mention the API key?").
    *   *Action*: Vector search on `meetings_transcript` index.
*   **`config_search`**: User asks about meeting logistics (e.g., "When is the All Hands?").
    *   *Action*: Vector search on `meetings_config` (title/agenda) or exact match on title.
*   **`organizer_filter`**: User asks for meetings by host (e.g., "Meetings organized by Carol").
    *   *Action*: Filter by `organizer` field.
*   **`attendee_filter`**: User asks for meetings with specific people (e.g., "Meetings with Dave").
    *   *Action*: Filter where `attendees` contains target.
*   **`recent`**: User asks for latest meetings (e.g., "Last week's meetings").
    *   *Action*: Filter by `start_time`.

**LLM Analyzer Prompt:**
> "Analyze the meeting search query. Extract `strategy` (transcript_search, config_search, organizer_filter, attendee_filter, recent), `person_name`, and `refined_query`."

---

### **3.4 Domain: People (`search_people`)**

**Objective**: Find colleagues based on name, role, or expertise.

**Proposed Strategies:**
*   **`name_exact`**: User looks for a specific person (e.g., "Find John Doe").
    *   *Action*: Fuzzy string match on `display_name` or `username`.
*   **`role_filter`**: User looks for a job title (e.g., "Who is the CTO?").
    *   *Action*: Filter/Search by `title` field.
*   **`skill_semantic`**: User looks for expertise (e.g., "Who knows Python?").
    *   *Action*: Vector search on `skills` and `bio`.
*   **`department_filter`**: User looks for teams (e.g., "People in HR").
    *   *Action*: Filter by `department`.

**LLM Analyzer Prompt:**
> "Analyze the people search query. Extract `strategy` (name_exact, role_filter, skill_semantic, department_filter), `name`, `role`, `department`, and `refined_query`."

---

## **4. Implementation Roadmap**

1.  **Refactor `src/core/tools.py`**:
    *   Create a shared `QueryAnalyzer` helper class or function that takes a prompt and returns the structured JSON strategy.
    *   Update each `search_*` tool to use this analyzer.
2.  **Update `SearchEngine`**:
    *   Ensure `_add_to_index` stores necessary metadata (author, timestamp, file_type) to support the filtering strategies.
3.  **Testing**:
    *   Verify that "Show me PDF files" triggers `type_filter` and not a generic semantic search for "PDF".
