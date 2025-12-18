from pydantic import BaseModel, Field
from typing import Any
from .tool_registry import registry
from ..sandbox.base import SandboxInterface
from .search_engine import SearchEngine

class ReadFileInput(BaseModel):
    path: str = Field(..., description="The path to the file to read.")

@registry.register(name="read_file", args_schema=ReadFileInput)
def read_file(path: str, sandbox: SandboxInterface) -> str:
    """Reads the content of a file from the sandbox."""
    return sandbox.read_file(path)

class ListFilesInput(BaseModel):
    path: str = Field(".", description="The path to list files from.")

@registry.register(name="list_files", args_schema=ListFilesInput)
def list_files(path: str, sandbox: SandboxInterface) -> str:
    """Lists files in a directory in the sandbox."""
    files = sandbox.list_files(path)
    return "\n".join(files)

class ExecuteCommandInput(BaseModel):
    command: str = Field(..., description="The shell command to execute.")

@registry.register(name="execute_command", args_schema=ExecuteCommandInput)
def execute_command(command: str, sandbox: SandboxInterface) -> str:
    """Executes a shell command in the sandbox."""
    return sandbox.execute_command(command)

class ExecutePythonInput(BaseModel):
    code: str = Field(..., description="The Python code to execute.")

@registry.register(name="execute_python", args_schema=ExecutePythonInput)
def execute_python(code: str, sandbox: SandboxInterface) -> str:
    """Executes Python code in the sandbox and returns stdout, stderr, and created files."""
    import uuid
    
    # 1. Write code to a file
    run_id = uuid.uuid4().hex[:8]
    script_name = f"script_{run_id}.py"
    stdout_name = f"stdout_{run_id}.txt"
    stderr_name = f"stderr_{run_id}.txt"
    
    sandbox.write_file(script_name, code)
    
    # 2. Snapshot files before (top-level only for now)
    try:
        files_before = set(sandbox.list_files("."))
    except Exception:
        files_before = set()
        
    # 3. Execute with redirection
    # We use a wrapper command to ensure we capture exit code or handle crashes?
    # Simple redirection is enough for stdout/stderr.
    sandbox.execute_command(f"python {script_name} > {stdout_name} 2> {stderr_name}")
    
    # 4. Read outputs
    try:
        stdout = sandbox.read_file(stdout_name)
    except Exception:
        stdout = ""
        
    try:
        stderr = sandbox.read_file(stderr_name)
    except Exception:
        stderr = ""
        
    # 5. Snapshot files after
    try:
        files_after = set(sandbox.list_files("."))
    except Exception:
        files_after = set()
        
    # 6. Determine created files
    # Exclude our infrastructure files
    infra_files = {script_name, stdout_name, stderr_name}
    created_files = list(files_after - files_before - infra_files)
    
    # 7. Cleanup (optional, but good for hygiene)
    # sandbox.execute_command(f"rm {script_name} {stdout_name} {stderr_name}")
    
    output_parts = []
    if stdout:
        output_parts.append(f"STDOUT:\n{stdout}")
    if stderr:
        output_parts.append(f"STDERR:\n{stderr}")
    if created_files:
        output_parts.append(f"Created Files:\n" + "\n".join(created_files))
        
    if not output_parts:
        return "Execution completed with no output."
        
    return "\n\n".join(output_parts)

# --- Search Tools ---

class SearchFileInput(BaseModel):
    query: str = Field(..., description="The search query.")
    full_content: bool = Field(False, description="Whether to search full content (True) or just snippets (False).")

@registry.register(name="search_file", args_schema=SearchFileInput)
async def search_file(query: str, full_content: bool, search_engine: SearchEngine) -> str:
    """Searches for files based on content or snippets."""
    index_name = "file_contents" if full_content else "file_snippets"
    results = await search_engine.search(index_name, query)
    return str(results)

from .llm_provider import Message
from .logger import debug_logger
import json

class SearchEmailInput(BaseModel):
    query: str = Field(None, description="The search query. If empty, lists recent emails.")

@registry.register(name="search_email", args_schema=SearchEmailInput)
async def search_email(search_engine: SearchEngine, query: str = None) -> str:
    """Searches emails. Uses LLM to optimize the search strategy."""
    
    # 1. Helper to get all user's emails
    def get_all_my_emails():
        if not search_engine.current_user_id:
            return []
        user_id = search_engine.current_user_id
        
        # Resolve user email to match TenantConfig's ID-to-Email conversion
        user = next((u for u in search_engine.tenant.users if u.id == user_id), None)
        if not user:
            return []
            
        user_email = user.profile.email
        if not user_email:
             user_email = f"{user.username}@{search_engine.tenant.domain}"

        my_emails = []
        for email in search_engine.tenant.emails:
            # Check against email address OR user_id (just in case)
            if (email.from_user == user_email or email.from_user == user_id or
                user_email in email.to_users or user_id in email.to_users or
                user_email in email.cc_users or user_id in email.cc_users or
                user_email in email.bcc_users or user_id in email.bcc_users):
                my_emails.append(email)
        # Sort by timestamp descending
        my_emails.sort(key=lambda x: x.timestamp, reverse=True)
        return my_emails

    if not query:
        emails = get_all_my_emails()
        return str([e.model_dump() for e in emails[:20]])

    # 2. LLM Analysis
    prompt = f"""
    You are an expert search optimizer. Analyze the user's email search query: "{query}"
    
    Determine the best search strategy. Return a JSON object with:
    - "strategy": One of ["recent", "semantic", "sender_filter", "hybrid"]
    - "refined_query": The optimized query string for semantic search (if applicable).
    - "sender_name": The name of the sender if strategy is "sender_filter" or "hybrid".
    
    Rules:
    - If user asks for "recent emails", "my emails", "latest emails" -> strategy: "recent"
    - If user asks for emails from a specific person (e.g. "from boss", "emails by John") -> strategy: "sender_filter"
    - If user asks for a topic (e.g. "project alpha", "budget") -> strategy: "semantic"
    - If user asks for "recent emails about X" -> strategy: "hybrid" (semantic + sort)
    """
    
    messages = [Message(role="system", content=prompt)]
    
    try:
        response = await llm.generate(messages, tools=[])
        analysis = response.content
        # Clean up markdown code blocks if present
        if "```json" in analysis:
            analysis = analysis.split("```json")[1].split("```")[0]
        elif "```" in analysis:
            analysis = analysis.split("```")[1].split("```")[0]
            
        plan = json.loads(analysis)
        debug_logger.log_tool_result("search_email_optimizer", str(plan))
        
        strategy = plan.get("strategy", "semantic")
        refined_query = plan.get("refined_query", query)
        sender_name = plan.get("sender_name")
        
        all_emails = get_all_my_emails()
        
        if strategy == "recent":
            return str([e.model_dump() for e in all_emails[:20]])
            
        elif strategy == "sender_filter":
            matches = []
            # Resolve sender
            sender_id = None
            if sender_name:
                for user in search_engine.tenant.users:
                    if (sender_name.lower() in user.username.lower() or 
                        sender_name.lower() in user.profile.name.display_name.lower() or
                        (user.profile.title and sender_name.lower() in user.profile.title.lower())): 
                        sender_id = user.id
                        break
            
            for email in all_emails:
                if sender_id and email.from_user == sender_id:
                    matches.append(email)
                elif sender_name and sender_name.lower() in email.from_user.lower():
                    matches.append(email)
            return str([e.model_dump() for e in matches[:20]])
            
        elif strategy == "semantic":
            results = await search_engine.search("emails", refined_query, top_k=20)
            return str(results)
            
        elif strategy == "hybrid":
            results = await search_engine.search("emails", refined_query, top_k=50)
            results.sort(key=lambda x: x['metadata']['timestamp'], reverse=True)
            return str(results[:20])
            
    except Exception as e:
        debug_logger.log_tool_result("search_email_error", str(e))
        # Fallback to basic semantic search
        results = await search_engine.search("emails", query, top_k=20)
        return str(results)

    return "Error: Unreachable code" 

# Removed duplicate search_email_v2 and merged logic into search_email above
# The previous implementation had a placeholder search_email and a v2.
# I am cleaning this up to have just one robust search_email.

# ... (rest of the file)
    """Searches emails. Uses LLM to optimize the search strategy."""
    
    # 1. Helper to get all user's emails
    def get_all_my_emails():
        if not search_engine.current_user_id:
            return []
        user_id = search_engine.current_user_id
        my_emails = []
        for email in search_engine.tenant.emails:
            if (email.from_user == user_id or 
                user_id in email.to_users or 
                user_id in email.cc_users or 
                user_id in email.bcc_users):
                my_emails.append(email)
        # Sort by timestamp descending
        my_emails.sort(key=lambda x: x.timestamp, reverse=True)
        return my_emails

    if not query:
        emails = get_all_my_emails()
        return str([e.model_dump() for e in emails[:20]])

    # 2. LLM Analysis
    prompt = f"""
    You are an expert search optimizer. Analyze the user's email search query: "{query}"
    
    Determine the best search strategy. Return a JSON object with:
    - "strategy": One of ["recent", "semantic", "sender_filter", "hybrid"]
    - "refined_query": The optimized query string for semantic search (if applicable).
    - "sender_name": The name of the sender if strategy is "sender_filter" or "hybrid".
    
    Rules:
    - If user asks for "recent emails", "my emails", "latest emails" -> strategy: "recent"
    - If user asks for emails from a specific person (e.g. "from boss", "emails by John") -> strategy: "sender_filter"
    - If user asks for a topic (e.g. "project alpha", "budget") -> strategy: "semantic"
    - If user asks for "recent emails about X" -> strategy: "hybrid" (semantic + sort)
    """
    
    messages = [Message(role="system", content=prompt)]
    # We need a way to call LLM. The `llm` object passed here should be the provider.
    # We'll assume it has a `generate` method but we need to be careful about the signature.
    # The `generate` method takes `history` and `tools`. We pass empty tools.
    
    try:
        response = await llm.generate(messages, tools=[])
        analysis = response.content
        # Clean up markdown code blocks if present
        if "```json" in analysis:
            analysis = analysis.split("```json")[1].split("```")[0]
        elif "```" in analysis:
            analysis = analysis.split("```")[1].split("```")[0]
            
        plan = json.loads(analysis)
        debug_logger.log_tool_result("search_email_optimizer", str(plan))
        
        strategy = plan.get("strategy", "semantic")
        refined_query = plan.get("refined_query", query)
        sender_name = plan.get("sender_name")
        
        all_emails = get_all_my_emails()
        
        if strategy == "recent":
            return str([e.model_dump() for e in all_emails[:20]])
            
        elif strategy == "sender_filter":
            matches = []
            # Resolve sender
            sender_id = None
            if sender_name:
                for user in search_engine.tenant.users:
                    if (sender_name.lower() in user.username.lower() or 
                        sender_name.lower() in user.profile.name.display_name.lower() or
                        (user.profile.title and sender_name.lower() in user.profile.title.lower())): # Handle "boss" -> "VP" mapping? LLM should handle this mapping ideally, but we don't have the org chart in LLM context here easily unless we pass it.
                        # Actually, "boss's boss" is hard without context.
                        # But let's assume LLM extracted "Big Boss" or "VP".
                        sender_id = user.id
                        break
            
            for email in all_emails:
                if sender_id and email.from_user == sender_id:
                    matches.append(email)
                elif sender_name and sender_name.lower() in email.from_user.lower():
                    matches.append(email)
            return str([e.model_dump() for e in matches[:20]])
            
        elif strategy == "semantic":
            results = await search_engine.search("emails", refined_query, top_k=20)
            return str(results)
            
        elif strategy == "hybrid":
            # Semantic search first, then sort by time?
            # Or filter by time then semantic?
            # Usually "recent emails about X" means semantic match is important, but recency is tie breaker.
            results = await search_engine.search("emails", refined_query, top_k=50)
            # The results are dicts with 'score' and 'metadata'.
            # We can sort them by timestamp in metadata.
            results.sort(key=lambda x: x['metadata']['timestamp'], reverse=True)
            return str(results[:20])
            
    except Exception as e:
        debug_logger.log_tool_result("search_email_error", str(e))
        # Fallback to basic semantic search
        results = await search_engine.search("emails", query, top_k=20)
        return str(results)

    return "Error: Unreachable code"

class SearchChatInput(BaseModel):
    query: str = Field(..., description="The search query.")

@registry.register(name="search_chat", args_schema=SearchChatInput)
async def search_chat(query: str, search_engine: SearchEngine) -> str:
    """Searches 1:1 chats."""
    results = await search_engine.search("chats", query)
    return str(results)

class SearchGroupChatInput(BaseModel):
    query: str = Field(..., description="The search query.")

@registry.register(name="search_group_chat", args_schema=SearchGroupChatInput)
async def search_group_chat(query: str, search_engine: SearchEngine) -> str:
    """Searches group chats."""
    results = await search_engine.search("group_chats", query)
    return str(results)

class SearchChannelInput(BaseModel):
    query: str = Field(..., description="The search query.")

@registry.register(name="search_channel", args_schema=SearchChannelInput)
async def search_channel(query: str, search_engine: SearchEngine) -> str:
    """Searches channels."""
    results = await search_engine.search("channels", query)
    return str(results)

class SearchMeetingInput(BaseModel):
    query: str = Field(..., description="The search query.")
    transcript: bool = Field(False, description="Whether to search transcripts (True) or just config/agenda (False).")

@registry.register(name="search_meeting", args_schema=SearchMeetingInput)
async def search_meeting(query: str, transcript: bool, search_engine: SearchEngine) -> str:
    """Searches meetings."""
    index_name = "meetings_transcript" if transcript else "meetings_config"
    results = await search_engine.search(index_name, query)
    return str(results)

# --- User Context Tools ---

class SearchPeopleInput(BaseModel):
    query: str = Field(..., description="The name, username, or email to search for.")

@registry.register(name="search_people", args_schema=SearchPeopleInput)
async def search_people(query: str, search_engine: SearchEngine) -> str:
    """Searches for colleagues/users in the tenant using semantic search."""
    results = await search_engine.search("users", query)
    return str(results)
