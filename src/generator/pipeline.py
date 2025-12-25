import os
import json
import yaml
import datetime
from typing import List, Dict, Any
from pydantic import BaseModel
from .models import StoryConfig, GenerationOutput
from ..core.llm_provider import LLMProvider
from ..config.tenant_config import TenantConfig, UserInfo, Email, Chat, GroupChat, Meeting, FileMetadata

class DataGenerator:
    def __init__(self, llm: LLMProvider, output_dir: str = "examples/tenants", prompts_path: str = "examples/generation/default_prompts.yaml"):
        self.llm = llm
        self.output_dir = output_dir
        self.prompts = self._load_prompts(prompts_path)

    def _load_prompts(self, path: str) -> Dict[str, str]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Prompts file not found: {path}")
        with open(path, "r") as f:
            return yaml.safe_load(f)

    async def generate_tenant(self, story: StoryConfig) -> GenerationOutput:
        tenant_id = story.company_name.lower().replace(" ", "-") + "-" + datetime.datetime.now().strftime("%Y%m%d")
        base_path = os.path.join(self.output_dir, tenant_id)
        os.makedirs(base_path, exist_ok=True)
        os.makedirs(os.path.join(base_path, "config"), exist_ok=True)
        os.makedirs(os.path.join(base_path, "docs"), exist_ok=True) # For file content if we store it separately

        print(f"Generating tenant: {tenant_id}")

        # 1. Generate Users
        users = await self._generate_users(story, tenant_id)
        
        if not users:
            print("Error: No users generated. Aborting.")
            return GenerationOutput(
                tenant_id=tenant_id, 
                base_path=base_path, 
                summary="Failed to generate users. Check LLM output or prompts."
            )

        # Save users to tenant.yaml immediately
        tenant_config = TenantConfig(
            id=tenant_id,
            domain=f"{tenant_id}.com",
            users=users,
            emails=[],
            chats=[],
            group_chats=[],
            meetings=[],
            files_metadata=[],
            channels=[]
        )
        tenant_data = tenant_config.model_dump(exclude={'emails', 'chats', 'group_chats', 'meetings', 'channels', 'files_metadata'}, exclude_none=True)
        with open(os.path.join(base_path, "tenant.yaml"), "w") as f:
            yaml.dump(tenant_data, f)
        
        print(f"Users generated and saved to {os.path.join(base_path, 'tenant.yaml')}")

        # Initialize config files
        for config_file in ["emails.yaml", "chats.yaml", "group_chats.yaml", "meetings.yaml", "files.yaml"]:
            with open(os.path.join(base_path, "config", config_file), "w") as f:
                f.write("[]\n") # Initialize as empty list, but we will append items manually or rewrite

        # 2. Generate Content (Emails, Chats, Meetings, Files)
        # We pass base_path to write incrementally
        await self._generate_content(story, users, base_path)

        # 4. Generate Eval Set
        # Reload full config to generate eval set? Or just use what we have.
        # For now, let's skip reloading everything to save memory as requested.
        # We can generate eval set based on a summary or just skip it for this optimization step.
        # But the original code did it. Let's try to do it with minimal data.
        
        # await self._generate_eval_set(story, tenant_config, base_path)

        return GenerationOutput(
            tenant_id=tenant_id,
            base_path=base_path,
            summary=f"Generated tenant {tenant_id} with users and content."
        )

    async def _generate_users(self, story: StoryConfig, tenant_id: str) -> List[UserInfo]:
        prompt = self.prompts['generate_users'].format(
            company_name=story.company_name,
            industry=story.industry,
            company_size=story.company_size,
            description=story.description,
            domain=f"{tenant_id}.com",
            num_users=5 # Start small
        )
        
        response = await self.llm.get_completion([{"role": "user", "content": prompt}])
        data = self._parse_json(response)
        
        user_list = []
        if isinstance(data, list):
            user_list = data
        elif isinstance(data, dict):
            user_list = data.get("users", [])
            
        users = []
        for u in user_list:
            # Validate/Fix fields
            if "profile" not in u:
                # Reshape flat structure to nested profile
                profile = {
                    "email": u.get("email"),
                    "name": u.get("name"),
                    "title": u.get("title"),
                    "department": u.get("department"),
                    "manager_id": u.get("manager_id"),
                    "skills": u.get("skills", []),
                    "location": u.get("location", "San Francisco"),
                    "timezone": u.get("timezone", "America/Los_Angeles")
                }
                u["profile"] = profile
            
            users.append(UserInfo(**u))
        return users

    def _append_to_yaml(self, item: BaseModel, path: str):
        # This is a hacky way to append to a YAML list without parsing the whole file
        # We assume the file starts with "[]" or is a list
        # If it's "[]", we replace it with the first item
        # If it's a list, we append
        
        data = item.model_dump(exclude_none=True)
        yaml_str = yaml.dump([data], sort_keys=False)
        
        # Check if file is empty or just "[]"
        if os.path.exists(path):
            with open(path, "r") as f:
                content = f.read().strip()
            
            if content == "[]":
                with open(path, "w") as f:
                    f.write(yaml_str)
            else:
                # Append
                with open(path, "a") as f:
                    f.write(yaml_str)
        else:
            with open(path, "w") as f:
                f.write(yaml_str)

    async def _generate_content(self, story: StoryConfig, users: List[UserInfo], base_path: str):
        # We don't store lists in memory anymore
        
        users_context = "\n".join([f"{u.id}: {u.profile.name.display_name} ({u.profile.title})" for u in users])
        start_date = datetime.datetime.now() - datetime.timedelta(days=story.duration_days)
        
        storyline_history = []
        
        # Daily Simulation Loop
        for day in range(story.duration_days):
            current_date = start_date + datetime.timedelta(days=day)
            date_str = current_date.strftime("%Y-%m-%d")
            print(f"Simulating Day {day+1}/{story.duration_days}: {date_str}")
            
            # 1. Generate Daily Story
            daily_prompt = self.prompts['generate_daily_story'].format(
                company_name=story.company_name,
                description=story.description,
                date=date_str,
                key_events="\n".join(story.key_events),
                storyline_history="\n".join(storyline_history[-5:]) # Keep last 5 days context
            )
            
            daily_resp = await self.llm.get_completion([{"role": "user", "content": daily_prompt}])
            daily_data = self._parse_json(daily_resp)
            daily_events = daily_data.get("daily_events", [])
            
            if not daily_events:
                print(f"No events generated for {date_str}")
                continue
                
            # Update history
            storyline_history.extend([f"[{date_str}] {e}" for e in daily_events])
            current_scenario = "\n".join(daily_events)
            history_context = "\n".join(storyline_history[-10:]) # Pass more context to content generators

            # 2. Generate Content based on Daily Events
            
            # --- Emails ---
            email_summary_prompt = self.prompts['generate_email_summaries'].format(
                event_description=current_scenario,
                storyline_history=history_context,
                users_context=users_context,
                date=date_str
            )
            email_summary_resp = await self.llm.get_completion([{"role": "user", "content": email_summary_prompt}])
            email_summaries = self._parse_json(email_summary_resp)
            
            if isinstance(email_summaries, list):
                for summary in email_summaries:
                    # Generate full content
                    from_user_obj = next((u for u in users if u.id == summary.get('from_user')), None)
                    to_users_objs = [u for u in users if u.id in summary.get('to_users', [])]
                    
                    from_name = from_user_obj.profile.name.display_name if from_user_obj else "Unknown"
                    from_title = from_user_obj.profile.title if from_user_obj else "Unknown"
                    to_names = ", ".join([u.profile.name.display_name for u in to_users_objs])
                    
                    content_prompt = self.prompts['generate_email_content'].format(
                        subject=summary.get('subject'),
                        from_user_name=from_name,
                        from_user_title=from_title,
                        to_users_names=to_names,
                        context_summary=summary.get('context_summary'),
                        storyline_history=history_context
                    )
                    content_resp = await self.llm.get_completion([{"role": "user", "content": content_prompt}])
                    content_data = self._parse_json(content_resp)
                    
                    # Construct Email object
                    email_obj = Email(
                        id=summary.get('id'),
                        from_user=summary.get('from_user'),
                        to_users=summary.get('to_users', []),
                        cc_users=summary.get('cc_users', []),
                        subject=summary.get('subject'),
                        body=content_data.get('body', "Content generation failed."),
                        timestamp=summary.get('timestamp', current_date.isoformat())
                    )
                    
                    # Print preview
                    print(f"\n[Email] {email_obj.subject} ({len(email_obj.body)} chars)")
                    print(f"Body Preview: {email_obj.body[:250]}...")
                    
                    # Append to file
                    self._append_to_yaml(email_obj, os.path.join(base_path, "config", "emails.yaml"))

            # --- Chats ---
            chat_summary_prompt = self.prompts['generate_chat_summaries'].format(
                event_description=current_scenario,
                users_context=users_context,
                date=date_str
            )
            chat_summary_resp = await self.llm.get_completion([{"role": "user", "content": chat_summary_prompt}])
            chat_summaries = self._parse_json(chat_summary_resp)
            
            if isinstance(chat_summaries, list):
                for summary in chat_summaries:
                    participants_objs = [u for u in users if u.id in summary.get('participants', [])]
                    participants_names = ", ".join([u.profile.name.display_name for u in participants_objs])
                    
                    content_prompt = self.prompts['generate_chat_content'].format(
                        participants_names=participants_names,
                        context_summary=summary.get('context_summary'),
                        date=date_str
                    )
                    content_resp = await self.llm.get_completion([{"role": "user", "content": content_prompt}])
                    content_data = self._parse_json(content_resp)
                    
                    messages = []
                    participants = summary.get('participants', [])
                    is_direct_chat = len(participants) == 2
                    
                    for msg in content_data.get('messages', []):
                        from_user = msg.get('from_user')
                        to_user = None
                        
                        if is_direct_chat:
                            # Infer to_user for 1:1 chats
                            for p in participants:
                                if p != from_user:
                                    to_user = p
                                    break
                        
                        messages.append({
                            "from_user": from_user,
                            "to_user": to_user,
                            "content": msg.get('content'),
                            "timestamp": msg.get('timestamp')
                        })
                        
                    if summary.get('type') == 'group_chat':
                        chat_obj = GroupChat(
                            id=summary.get('id'),
                            name=summary.get('name', 'Group Chat'),
                            participants=summary.get('participants', []),
                            messages=messages
                        )
                        print(f"\n[Group Chat] {chat_obj.name} ({len(messages)} msgs)")
                        if messages:
                            print(f"First Msg: {messages[0]['content'][:250]}...")
                        self._append_to_yaml(chat_obj, os.path.join(base_path, "config", "group_chats.yaml"))
                    else:
                        chat_obj = Chat(
                            id=summary.get('id'),
                            participants=summary.get('participants', []),
                            messages=messages
                        )
                        print(f"\n[Chat] {', '.join(chat_obj.participants)} ({len(messages)} msgs)")
                        if messages:
                            print(f"First Msg: {messages[0]['content'][:250]}...")
                        self._append_to_yaml(chat_obj, os.path.join(base_path, "config", "chats.yaml"))

            # --- Meetings ---
            meeting_summary_prompt = self.prompts['generate_meeting_summaries'].format(
                event_description=current_scenario,
                users_context=users_context,
                date=date_str
            )
            meeting_summary_resp = await self.llm.get_completion([{"role": "user", "content": meeting_summary_prompt}])
            meeting_summaries = self._parse_json(meeting_summary_resp)
            
            if isinstance(meeting_summaries, list):
                for summary in meeting_summaries:
                    participants_objs = [u for u in users if u.id in summary.get('attendee_ids', [])]
                    participants_names = ", ".join([u.profile.name.display_name for u in participants_objs])
                    
                    transcript_prompt = self.prompts['generate_meeting_transcript'].format(
                        title=summary.get('title'),
                        agenda=summary.get('agenda'),
                        participants_names=participants_names,
                        context_summary=summary.get('context_summary')
                    )
                    transcript_resp = await self.llm.get_completion([{"role": "user", "content": transcript_prompt}])
                    transcript_data = self._parse_json(transcript_resp)
                    
                    attendees = summary.get('attendee_ids', [])
                    organizer = attendees[0] if attendees else "unknown"

                    # Generate Meeting Chat
                    chat_prompt = self.prompts['generate_meeting_chat'].format(
                        title=summary.get('title'),
                        participants_names=participants_names,
                        context_summary=summary.get('context_summary'),
                        date=date_str
                    )
                    chat_resp = await self.llm.get_completion([{"role": "user", "content": chat_prompt}])
                    chat_data = self._parse_json(chat_resp)
                    
                    meeting_chat_messages = []
                    for msg in chat_data.get('messages', []):
                        meeting_chat_messages.append({
                            "from_user": msg.get('from_user'),
                            "to_user": None,
                            "content": msg.get('content'),
                            "timestamp": msg.get('timestamp')
                        })
                        
                    meeting_chat = GroupChat(
                        id=f"chat_{summary.get('id')}",
                        name=f"Chat: {summary.get('title')}",
                        participants=attendees,
                        messages=meeting_chat_messages
                    )

                    meeting_obj = Meeting(
                        id=summary.get('id'),
                        title=summary.get('title'),
                        organizer=organizer,
                        invitees=attendees,
                        attendees=attendees,
                        agenda=summary.get('agenda'),
                        start_time=summary.get('start_time'),
                        end_time=summary.get('end_time'),
                        location=summary.get('location', 'Online'),
                        transcript=transcript_data.get('transcript', "Transcript generation failed."),
                        chat=meeting_chat
                    )
                    
                    print(f"\n[Meeting] {meeting_obj.title}")
                    if meeting_obj.transcript:
                        print(f"Transcript Preview: {meeting_obj.transcript[:250]}...")
                    if meeting_obj.chat:
                        print(f"Chat Preview: {len(meeting_obj.chat.messages)} messages")
                    
                    self._append_to_yaml(meeting_obj, os.path.join(base_path, "config", "meetings.yaml"))
            
            # --- Files ---
            file_summary_prompt = self.prompts['generate_file_summaries'].format(
                event_description=current_scenario,
                users_context=users_context,
                date=date_str
            )
            file_summary_resp = await self.llm.get_completion([{"role": "user", "content": file_summary_prompt}])
            file_summaries = self._parse_json(file_summary_resp)
            
            if isinstance(file_summaries, list):
                for summary in file_summaries:
                    author_obj = next((u for u in users if u.id == summary.get('created_by')), None)
                    author_name = author_obj.profile.name.display_name if author_obj else "Unknown"
                    
                    content_prompt = self.prompts['generate_file_content'].format(
                        path=summary.get('path'),
                        author_name=author_name,
                        context_summary=summary.get('context_summary')
                    )
                    content_resp = await self.llm.get_completion([{"role": "user", "content": content_prompt}])
                    content_data = self._parse_json(content_resp)
                    
                    # Ensure path starts with data/
                    path = summary.get('path')
                    if not path.startswith('data/'):
                        path = f"data/{path}"
                        
                    # Write content immediately
                    file_path = os.path.join(base_path, path)
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    content = content_data.get('content', "Content generation failed.")
                    with open(file_path, "w") as f:
                        f.write(content)
                        
                    print(f"\n[File] {path}")
                    print(f"Content Preview: {content[:250]}...")

                    # Create and append metadata
                    meta = FileMetadata(
                        path=path,
                        created_by=summary.get('created_by'),
                        created_time=datetime.datetime.now().isoformat(),
                        snippet=summary.get('snippet') or summary.get('context_summary')
                    )
                    self._append_to_yaml(meta, os.path.join(base_path, "config", "files.yaml"))

        return

    async def _generate_eval_set(self, story: StoryConfig, tenant_config: TenantConfig, base_path: str):
        # Summarize data for the prompt
        data_summary = f"Users: {len(tenant_config.users)}\nEmails: {len(tenant_config.emails)}\nMeetings: {len(tenant_config.meetings)}"
        
        prompt = self.prompts['generate_eval_cases'].format(
            data_summary=data_summary,
            num_cases=5
        )
        
        response = await self.llm.get_completion([{"role": "user", "content": prompt}])
        cases = self._parse_json(response)
        
        # Save to eval_set.yaml
        # We need to match the EvaluationSet model structure
        # But for now, just saving the raw list is a good start, or adapting it.
        # Let's assume the output matches what we need or we wrap it.
        
        eval_data = {
            "id": f"eval-{tenant_config.id}",
            "cases": cases
        }
        
        with open(os.path.join(base_path, "eval_set.yaml"), "w") as f:
            yaml.dump(eval_data, f)

    def _parse_json(self, text: str) -> Any:
        import re
        import json
        
        # Try to find JSON block in markdown
        match = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1)
            
        text = text.strip()
        
        # Try to parse directly
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
            
        # Try to find start and end to handle extra text
        try:
            start_list = text.find("[")
            start_dict = text.find("{")
            
            if start_list == -1 and start_dict == -1:
                return {}
                
            # Determine if it starts as list or dict
            if start_list != -1 and (start_dict == -1 or start_list < start_dict):
                # It's a list
                end = text.rfind("]")
                if end != -1:
                    return json.loads(text[start_list:end+1])
            else:
                # It's a dict
                end = text.rfind("}")
                if end != -1:
                    return json.loads(text[start_dict:end+1])
                    
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            # print(f"Text was: {text[:100]}...")
            
        return {}

    def _save_list_to_yaml(self, items: List[BaseModel], path: str):
        data = [item.model_dump() for item in items]
        with open(path, "w") as f:
            yaml.dump(data, f)
