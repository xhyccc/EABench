from pydantic import BaseModel, Field
from typing import Any, Optional
from .tool_registry import registry
from ..sandbox.base import SandboxInterface
from .search_engine import SearchEngine
from .query_analyzer import QueryAnalyzer

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
    query: list[str] = Field(..., description="The list of search queries.")
    full_content: Optional[bool] = Field(False, description="Whether to search full content (True) or just snippets (False).")

@registry.register(name="search_file", args_schema=SearchFileInput)
async def search_file(query: list[str], search_engine: SearchEngine, query_analyzer: QueryAnalyzer, full_content: bool = False) -> str:
    """Searches for files based on content or snippets."""
    all_results = []
    for q in query:
        try:
            plan = await query_analyzer.analyze(q, "search_file", tool_name="search_file")
            strategy = plan.get("strategy", "semantic")
            refined_query = plan.get("refined_query", q)
            
            # TODO: Implement specific filtering logic for filename, author, type
            # For now, we map strategies to index selection or basic filtering
            
            index_name = "file_contents" if full_content else "file_snippets"
            
            if strategy == "filename_exact":
                # We can't easily do exact match with vector search unless we have metadata filtering
                # For now, we'll just use the refined query (filename) against snippets
                results = await search_engine.search("file_snippets", refined_query)
                all_results.append(f"Results for '{q}':\n{results}")
                
            elif strategy == "semantic":
                results = await search_engine.search(index_name, refined_query)
                all_results.append(f"Results for '{q}':\n{results}")
                
            else:
                # Fallback
                results = await search_engine.search(index_name, refined_query)
                all_results.append(f"Results for '{q}':\n{results}")
                
        except Exception as e:
            debug_logger.log_tool_result("search_file_error", str(e))
            index_name = "file_contents" if full_content else "file_snippets"
            results = await search_engine.search(index_name, q)
            all_results.append(f"Results for '{q}':\n{results}")

    return "\n\n".join(all_results)

from .llm_provider import Message
from .logger import debug_logger
import json

class SearchEmailInput(BaseModel):
    query: list[str] = Field(None, description="The list of search queries. If empty, lists recent emails.")

@registry.register(name="search_email", args_schema=SearchEmailInput)
async def search_email(search_engine: SearchEngine, query_analyzer: QueryAnalyzer, query: list[str] = None) -> str:
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

    all_results = []
    for q in query:
        # 2. LLM Analysis via QueryAnalyzer
        try:
            plan = await query_analyzer.analyze(q, "search_email", tool_name="search_email")
            
            strategy = plan.get("strategy", "semantic")
            refined_query = plan.get("refined_query", q)
            sender_name = plan.get("sender_name")
            
            all_emails = get_all_my_emails()
            
            if strategy == "recent":
                all_results.append(f"Results for '{q}':\n{[e.model_dump() for e in all_emails[:20]]}")
                
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
                all_results.append(f"Results for '{q}':\n{[e.model_dump() for e in matches[:20]]}")
                
            elif strategy == "semantic":
                results = await search_engine.search("emails", refined_query, top_k=20)
                all_results.append(f"Results for '{q}':\n{results}")
                
            elif strategy == "hybrid":
                results = await search_engine.search("emails", refined_query, top_k=50)
                results.sort(key=lambda x: x['metadata']['timestamp'], reverse=True)
                all_results.append(f"Results for '{q}':\n{results[:20]}")
                
        except Exception as e:
            debug_logger.log_tool_result("search_email_error", str(e))
            # Fallback to basic semantic search
            results = await search_engine.search("emails", q, top_k=20)
            all_results.append(f"Results for '{q}':\n{results}")

    return "\n\n".join(all_results) 

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

    # 2. LLM Analysis via QueryAnalyzer
    try:
        plan = await query_analyzer.analyze(query, "search_email", tool_name="search_email")
        
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

class SearchChatInput(BaseModel):
    query: list[str] = Field(..., description="The list of search queries.")

@registry.register(name="search_chat", args_schema=SearchChatInput)
async def search_chat(query: list[str], search_engine: SearchEngine, query_analyzer: QueryAnalyzer) -> str:
    """Searches 1:1 chats."""
    all_results = []
    for q in query:
        try:
            plan = await query_analyzer.analyze(q, "search_chat", tool_name="search_chat")
            refined_query = plan.get("refined_query", q)
            # TODO: Implement participant filtering
            results = await search_engine.search("chats", refined_query)
            all_results.append(f"Results for '{q}':\n{results}")
        except Exception:
            results = await search_engine.search("chats", q)
            all_results.append(f"Results for '{q}':\n{results}")
    return "\n\n".join(all_results)

class SearchGroupChatInput(BaseModel):
    query: list[str] = Field(..., description="The list of search queries.")

@registry.register(name="search_group_chat", args_schema=SearchGroupChatInput)
async def search_group_chat(query: list[str], search_engine: SearchEngine, query_analyzer: QueryAnalyzer) -> str:
    """Searches group chats."""
    all_results = []
    for q in query:
        try:
            plan = await query_analyzer.analyze(q, "search_chat", tool_name="search_group_chat") # Reuse chat prompt
            refined_query = plan.get("refined_query", q)
            results = await search_engine.search("group_chats", refined_query)
            all_results.append(f"Results for '{q}':\n{results}")
        except Exception:
            results = await search_engine.search("group_chats", q)
            all_results.append(f"Results for '{q}':\n{results}")
    return "\n\n".join(all_results)

class SearchChannelInput(BaseModel):
    query: list[str] = Field(..., description="The list of search queries.")

@registry.register(name="search_channel", args_schema=SearchChannelInput)
async def search_channel(query: list[str], search_engine: SearchEngine, query_analyzer: QueryAnalyzer) -> str:
    """Searches channels."""
    all_results = []
    for q in query:
        try:
            plan = await query_analyzer.analyze(q, "search_chat", tool_name="search_channel") # Reuse chat prompt
            refined_query = plan.get("refined_query", q)
            results = await search_engine.search("channels", refined_query)
            all_results.append(f"Results for '{q}':\n{results}")
        except Exception:
            results = await search_engine.search("channels", q)
            all_results.append(f"Results for '{q}':\n{results}")
    return "\n\n".join(all_results)

class SearchMeetingInput(BaseModel):
    query: list[str] = Field(..., description="The list of search queries.")
    transcript: Optional[bool] = Field(False, description="Whether to search transcripts (True) or just config/agenda (False).")

@registry.register(name="search_meeting", args_schema=SearchMeetingInput)
async def search_meeting(query: list[str], search_engine: SearchEngine, query_analyzer: QueryAnalyzer, transcript: bool = False) -> str:
    """Searches meetings."""
    index_name = "meetings_transcript" if transcript else "meetings_config"
    all_results = []
    for q in query:
        try:
            plan = await query_analyzer.analyze(q, "search_meeting", tool_name="search_meeting")
            refined_query = plan.get("refined_query", q)
            # TODO: Implement organizer/attendee filtering
            results = await search_engine.search(index_name, refined_query)
            all_results.append(f"Results for '{q}':\n{results}")
        except Exception:
            results = await search_engine.search(index_name, q)
            all_results.append(f"Results for '{q}':\n{results}")
    return "\n\n".join(all_results)

# --- User Context Tools ---

class SearchPeopleInput(BaseModel):
    query: list[str] = Field(..., description="The list of names, usernames, or emails to search for.")

@registry.register(name="search_people", args_schema=SearchPeopleInput)
async def search_people(query: list[str], search_engine: SearchEngine, query_analyzer: QueryAnalyzer) -> str:
    """Searches for colleagues/users in the tenant using semantic search."""
    all_results = []
    for q in query:
        try:
            plan = await query_analyzer.analyze(q, "search_people", tool_name="search_people")
            refined_query = plan.get("refined_query", q)
            # TODO: Implement role/department filtering
            results = await search_engine.search("users", refined_query)
            all_results.append(f"Results for '{q}':\n{results}")
        except Exception:
            results = await search_engine.search("users", q)
            all_results.append(f"Results for '{q}':\n{results}")
    return "\n\n".join(all_results)
