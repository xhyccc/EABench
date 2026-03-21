import numpy as np
import os
import pickle
from typing import List, Dict, Any, Tuple
from .embedding_provider import EmbeddingProvider
from ..config.tenant_config import TenantConfig
from ..sandbox.base import SandboxInterface

class SearchEngine:
    def __init__(self, tenant_config: TenantConfig, embedding_provider: EmbeddingProvider, sandbox: SandboxInterface, indices: Dict[str, Dict[str, Any]] = None):
        self.tenant = tenant_config
        self.embedding_provider = embedding_provider
        self.sandbox = sandbox
        
        # Indices
        if indices:
            self.indices = indices
        else:
            self.indices: Dict[str, Dict[str, Any]] = {
                "file_snippets": {"vectors": [], "data": []},
                "file_contents": {"vectors": [], "data": []},
                "emails": {"vectors": [], "data": []},
                "chats": {"vectors": [], "data": []},
                "group_chats": {"vectors": [], "data": []},
                "channels": {"vectors": [], "data": []},
                "meetings_config": {"vectors": [], "data": []},
                "meetings_transcript": {"vectors": [], "data": []},
                "users": {"vectors": [], "data": []},
            }
        self.current_user_id: str = None
        self.current_user_emails: List[str] = []

    def set_user_context(self, user_id: str):
        self.current_user_id = user_id
        self.current_user_emails = []
        if self.tenant:
            user = next((u for u in self.tenant.users if u.id == user_id), None)
            if user:
                if user.profile.email:
                    self.current_user_emails.append(user.profile.email)
                # Also add constructed email if needed
                constructed_email = f"{user.username}@{self.tenant.domain}"
                if constructed_email not in self.current_user_emails:
                    self.current_user_emails.append(constructed_email)

    async def index_all(self):
        # Check for cache
        if self.tenant.root_path:
            cache_dir = os.path.join(self.tenant.root_path, ".cache")
            model_name = self.embedding_provider.get_model_name()
            safe_model_name = "".join(c if c.isalnum() else "_" for c in model_name)
            cache_file = os.path.join(cache_dir, f"embeddings_{safe_model_name}.pkl")
            
            if os.path.exists(cache_file):
                print(f"Loading index from cache: {cache_file}")
                try:
                    with open(cache_file, "rb") as f:
                        self.indices = pickle.load(f)
                    return
                except Exception as e:
                    print(f"Failed to load cache: {e}")

        # Index File Snippets
        for file_meta in self.tenant.files_metadata:
            if file_meta.snippet:
                text = f"File: {file_meta.path}\n"
                if file_meta.created_by:
                    text += f"Created By: {file_meta.created_by}\n"
                if file_meta.last_modified_by:
                    text += f"Modified By: {file_meta.last_modified_by}\n"
                text += f"Snippet: {file_meta.snippet}"
                await self._add_to_index("file_snippets", text, file_meta.model_dump())

        # Index Users
        for user in self.tenant.users:
            # Construct a rich text representation for the user
            profile = user.profile
            text = f"Name: {profile.name.display_name}\n"
            text += f"Username: {user.username}\n"
            text += f"Email: {profile.email}\n"
            text += f"Title: {profile.title}\n"
            text += f"Department: {profile.department}\n"
            text += f"Location: {profile.location}\n"
            text += f"Skills: {', '.join(profile.skills)}\n"
            if profile.manager_id:
                text += f"Manager ID: {profile.manager_id}\n"
            
            await self._add_to_index("users", text, user.model_dump())

        # Index File Contents (read from sandbox)
        # Note: In a real system, we might not want to read ALL files into memory.
        # But for this bench, we assume small scale.
        try:
            # We need to know which files exist. We can use the metadata or list files.
            # Let's use metadata paths.
            for file_meta in self.tenant.files_metadata:
                try:
                    content = self.sandbox.read_file(file_meta.path)
                    text = f"File: {file_meta.path}\n"
                    if file_meta.created_by:
                        text += f"Created By: {file_meta.created_by}\n"
                    text += f"Content: {content}"
                    await self._add_to_index("file_contents", text, {"path": file_meta.path, "content": content})
                except Exception:
                    # File might not exist in sandbox yet or is a directory
                    pass
        except Exception as e:
            print(f"Warning: Failed to index file contents: {e}")

        # Index Emails
        for email in self.tenant.emails:
            text = f"ID: {email.id}\nFrom: {email.from_user}\nTo: {', '.join(email.to_users)}\n"
            if email.cc_users:
                text += f"CC: {', '.join(email.cc_users)}\n"
            if email.bcc_users:
                text += f"BCC: {', '.join(email.bcc_users)}\n"
            text += f"Date: {email.timestamp}\nSubject: {email.subject}\nBody: {email.body}"
            await self._add_to_index("emails", text, email.model_dump())

        # Index Chats
        for chat in self.tenant.chats:
            # Index each message or the whole chat? 
            # Let's index individual messages for better granularity
            for msg in chat.messages:
                text = f"Chat ID: {chat.id}\nParticipants: {', '.join(chat.participants)}\nDate: {msg.timestamp}\nFrom: {msg.from_user}\nContent: {msg.content}"
                await self._add_to_index("chats", text, {"chat_id": chat.id, "participants": chat.participants, **msg.model_dump()})

        # Index Group Chats
        for gc in self.tenant.group_chats:
            for msg in gc.messages:
                text = f"Group Chat ID: {gc.id}\nGroup: {gc.name}\nParticipants: {', '.join(gc.participants)}\nDate: {msg.timestamp}\nFrom: {msg.from_user}\nContent: {msg.content}"
                await self._add_to_index("group_chats", text, {"group_chat_id": gc.id, "participants": gc.participants, **msg.model_dump()})

        # Index Channels
        for channel in self.tenant.channels:
            for post in channel.posts:
                text = f"Channel ID: {channel.id}\nChannel: {channel.name}\nParticipants: {', '.join(channel.participants)}\nDate: {post.timestamp}\nAuthor: {post.author}\nContent: {post.content}"
                await self._add_to_index("channels", text, {"channel_id": channel.id, "participants": channel.participants, **post.model_dump()})

        # Index Meetings
        for meeting in self.tenant.meetings:
            # Config (Agenda, Title)
            config_text = f"Meeting ID: {meeting.id}\nTitle: {meeting.title}\nAgenda: {meeting.agenda}\n"
            config_text += f"Organizer: {meeting.organizer}\n"
            config_text += f"Invitees: {', '.join(meeting.invitees)}\n"
            config_text += f"Attendees: {', '.join(meeting.attendees)}\n"
            config_text += f"Date: {meeting.start_time} to {meeting.end_time}\n"
            if meeting.location:
                config_text += f"Location: {meeting.location}\n"

            await self._add_to_index("meetings_config", config_text, meeting.model_dump(exclude={"transcript", "chat"}))
            
            # Transcript
            if meeting.transcript:
                transcript_text = f"Meeting ID: {meeting.id}\nTitle: {meeting.title}\nDate: {meeting.start_time}\n"
                transcript_text += f"Organizer: {meeting.organizer}\n"
                transcript_text += f"Attendees: {', '.join(meeting.attendees)}\n"
                transcript_text += f"Transcript:\n{meeting.transcript}"

                await self._add_to_index("meetings_transcript", transcript_text, {
                    "meeting_id": meeting.id, 
                    "transcript": meeting.transcript,
                    "organizer": meeting.organizer,
                    "invitees": meeting.invitees,
                    "attendees": meeting.attendees
                })

        # Save to cache
        if self.tenant.root_path:
            try:
                cache_dir = os.path.join(self.tenant.root_path, ".cache")
                model_name = self.embedding_provider.get_model_name()
                safe_model_name = "".join(c if c.isalnum() else "_" for c in model_name)
                cache_file = os.path.join(cache_dir, f"embeddings_{safe_model_name}.pkl")
                
                if not os.path.exists(cache_dir):
                    os.makedirs(cache_dir)
                with open(cache_file, "wb") as f:
                    pickle.dump(self.indices, f)
                print(f"Saved index to cache: {cache_file}")
            except Exception as e:
                print(f"Failed to save cache: {e}")

    async def _add_to_index(self, index_name: str, text: str, metadata: Dict[str, Any]):
        vector = await self.embedding_provider.get_embedding(text)
        self.indices[index_name]["vectors"].append(vector)
        self.indices[index_name]["data"].append(metadata)

    async def search(self, index_name: str, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        index = self.indices.get(index_name)
        if not index or not index["vectors"]:
            return []

        query_vector = await self.embedding_provider.get_embedding(query)
        
        # Cosine similarity
        vectors = np.array(index["vectors"])
        query_vector = np.array(query_vector)
        
        # Normalize
        norm_vectors = np.linalg.norm(vectors, axis=1)
        norm_query = np.linalg.norm(query_vector)
        
        if norm_query == 0:
            return []
            
        similarities = np.dot(vectors, query_vector) / (norm_vectors * norm_query)
        
        # Get top indices
        top_indices = np.argsort(similarities)[::-1]
        
        results = []
        count = 0
        for idx in top_indices:
            if count >= top_k:
                break
                
            metadata = index["data"][idx]
            
            # Filter by user context
            if self.current_user_id:
                if not self._is_user_allowed(index_name, metadata, self.current_user_id):
                    continue
            
            results.append({
                "score": float(similarities[idx]),
                "metadata": metadata
            })
            count += 1
            
        return results

    def _is_user_allowed(self, index_name: str, metadata: Dict[str, Any], user_id: str) -> bool:
        if index_name == "emails":
            # Check ID
            if (user_id == metadata.get("from_user") or 
                user_id in metadata.get("to_users", []) or 
                user_id in metadata.get("cc_users", []) or 
                user_id in metadata.get("bcc_users", [])):
                return True
            
            # Check Emails
            for email in self.current_user_emails:
                if (email == metadata.get("from_user") or 
                    email in metadata.get("to_users", []) or 
                    email in metadata.get("cc_users", []) or 
                    email in metadata.get("bcc_users", [])):
                    return True
            
            return False
        
        elif index_name in ["chats", "group_chats", "channels"]:
            return user_id in metadata.get("participants", [])
            
        elif index_name in ["meetings_config", "meetings_transcript"]:
            return (user_id == metadata.get("organizer") or 
                    user_id in metadata.get("invitees", []) or 
                    user_id in metadata.get("attendees", []))
                    
        return True # Allow others (files) by default
