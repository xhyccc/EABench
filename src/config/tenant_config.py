from typing import List, Dict, Optional
from pydantic import BaseModel, Field
import yaml
import os

class UserName(BaseModel):
    display_name: str
    first_name: str
    last_name: str
    nickname: Optional[str] = None

class UserProfile(BaseModel):
    email: str
    name: UserName
    manager_id: Optional[str] = None
    skip_manager_id: Optional[str] = None
    department: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    title: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None

class UserInfo(BaseModel):
    id: str
    username: str
    groups: List[str] = Field(default_factory=list)
    profile: UserProfile

class FileMetadata(BaseModel):
    path: str
    created_by: Optional[str] = None
    created_time: Optional[str] = None
    last_modified_by: Optional[str] = None
    last_modified_time: Optional[str] = None
    snippet: Optional[str] = None

class ChatMessage(BaseModel):
    from_user: str
    to_user: Optional[str] = None
    content: str
    timestamp: str

class Chat(BaseModel):
    id: str
    participants: List[str]
    messages: List[ChatMessage] = Field(default_factory=list)

class GroupChat(BaseModel):
    id: str
    name: str
    participants: List[str]
    messages: List[ChatMessage] = Field(default_factory=list)

class Meeting(BaseModel):
    id: str
    title: str
    organizer: str
    invitees: List[str] = Field(default_factory=list)
    attendees: List[str] = Field(default_factory=list)
    start_time: str
    end_time: str
    agenda: str
    transcript: Optional[str] = None
    chat: Optional[GroupChat] = None

class Email(BaseModel):
    id: str
    from_user: str
    to_users: List[str]
    cc_users: List[str] = Field(default_factory=list)
    bcc_users: List[str] = Field(default_factory=list)
    subject: str
    body: str
    timestamp: str

class ChannelPost(BaseModel):
    id: str
    author: str
    content: str
    timestamp: str

class Channel(BaseModel):
    id: str
    name: str
    participants: List[str]
    posts: List[ChannelPost] = Field(default_factory=list)

class TenantConfig(BaseModel):
    id: str
    domain: str = "example.com"
    users: List[UserInfo] = Field(default_factory=list)
    files_metadata: List[FileMetadata] = Field(default_factory=list)
    
    # Office Automation Configs
    chats: List[Chat] = Field(default_factory=list)
    group_chats: List[GroupChat] = Field(default_factory=list)
    meetings: List[Meeting] = Field(default_factory=list)
    emails: List[Email] = Field(default_factory=list)
    channels: List[Channel] = Field(default_factory=list)

    resource_limits: Dict[str, str] = Field(default_factory=dict)
    
    # Internal path to the data directory
    data_path: Optional[str] = None

    @classmethod
    def from_yaml(cls, path: str) -> "TenantConfig":
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        
        config = cls(**data)
        
        # Resolve paths relative to the tenant.yaml file
        base_dir = os.path.dirname(os.path.abspath(path))
        config_dir = os.path.join(base_dir, "config")
        data_dir = os.path.join(base_dir, "data")
        
        # Helper to load list of models from yaml
        def load_config_list(filename: str, model_cls):
            file_path = os.path.join(config_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    items = yaml.safe_load(f)
                    if items:
                        return [model_cls(**item) for item in items]
            return []

        # Load file metadata
        config.files_metadata = load_config_list("files.yaml", FileMetadata)
        
        # Load Office Automation Configs
        config.chats = load_config_list("chats.yaml", Chat)
        config.group_chats = load_config_list("group_chats.yaml", GroupChat)
        config.meetings = load_config_list("meetings.yaml", Meeting)
        config.emails = load_config_list("emails.yaml", Email)
        config.channels = load_config_list("channels.yaml", Channel)
        
        # Resolve User IDs to Emails in Email objects
        user_email_map = {}
        for user in config.users:
            # Use profile email if available, otherwise construct from username + domain
            email = user.profile.email
            if not email:
                email = f"{user.username}@{config.domain}"
            user_email_map[user.id] = email
            
        for email in config.emails:
            if email.from_user in user_email_map:
                email.from_user = user_email_map[email.from_user]
            
            new_to = []
            for u in email.to_users:
                new_to.append(user_email_map.get(u, u))
            email.to_users = new_to
            
            new_cc = []
            for u in email.cc_users:
                new_cc.append(user_email_map.get(u, u))
            email.cc_users = new_cc
            
            new_bcc = []
            for u in email.bcc_users:
                new_bcc.append(user_email_map.get(u, u))
            email.bcc_users = new_bcc
        
        # Set data path for sandbox to use
        if os.path.exists(data_dir):
            config.data_path = data_dir
            
        return config
