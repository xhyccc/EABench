"""Tests for src.config modules: TenantConfig and AgentConfig."""

import os
import pytest
import yaml
import tempfile

from src.generator.yaml_utils import yaml_dump

from src.config.tenant_config import (
    TenantConfig,
    UserInfo,
    UserProfile,
    UserName,
    FileMetadata,
    Chat,
    ChatMessage,
    GroupChat,
    Meeting,
    Email,
    Channel,
    ChannelPost,
)
from src.config.agent_config import (
    AgentConfig,
    ModelConfig,
    EmbeddingConfig,
    ToolConfig,
    FlowConfig,
    FlowStrategy,
    ProviderType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_tenant_yaml(tmp_path: str, extra: dict = None) -> str:
    """Write a minimal tenant.yaml to *tmp_path* and return its path."""
    data = {
        "id": "test-tenant",
        "domain": "example.com",
        "users": [
            {
                "id": "user1",
                "username": "alice",
                "groups": ["admin"],
                "profile": {
                    "email": "alice@example.com",
                    "name": {
                        "display_name": "Alice Smith",
                        "first_name": "Alice",
                        "last_name": "Smith",
                    },
                    "department": "Engineering",
                    "skills": ["Python", "Rust"],
                    "title": "Engineer",
                },
            }
        ],
    }
    if extra:
        data.update(extra)

    tenant_path = os.path.join(tmp_path, "tenant.yaml")
    with open(tenant_path, "w") as f:
        yaml_dump(data, f)

    # Create config and data dirs so from_yaml doesn't crash on missing dirs
    os.makedirs(os.path.join(tmp_path, "config"), exist_ok=True)
    os.makedirs(os.path.join(tmp_path, "data"), exist_ok=True)

    return tenant_path


def _make_agent_yaml(tmp_path: str) -> str:
    data = {
        "id": "test-agent",
        "version": "1.0",
        "model": {"provider": "openai", "name": "gpt-4o"},
        "system_prompt": "You are a helpful assistant. {user_profile}",
        "tools": {"definitions": ["read_file", "list_files"]},
        "flow": {"strategy": "react", "max_turns": 5},
    }
    path = os.path.join(tmp_path, "agent.yaml")
    with open(path, "w") as f:
        yaml_dump(data, f)
    return path


# ---------------------------------------------------------------------------
# TenantConfig tests
# ---------------------------------------------------------------------------


class TestTenantConfigDirect:
    """Test TenantConfig created directly (no YAML loading)."""

    def test_minimal_construction(self):
        cfg = TenantConfig(id="t1")
        assert cfg.id == "t1"
        assert cfg.domain == "example.com"
        assert cfg.users == []
        assert cfg.files_metadata == []
        assert cfg.chats == []

    def test_with_users(self):
        user = UserInfo(
            id="u1",
            username="bob",
            profile=UserProfile(
                email="bob@test.com",
                name=UserName(display_name="Bob", first_name="Bob", last_name="Jones"),
            ),
        )
        cfg = TenantConfig(id="t1", users=[user])
        assert len(cfg.users) == 1
        assert cfg.users[0].username == "bob"
        assert cfg.users[0].profile.email == "bob@test.com"

    def test_with_files_metadata(self):
        fm = FileMetadata(
            path="data/docs/hello.txt",
            created_by="user1",
            snippet="Hello world",
        )
        cfg = TenantConfig(id="t1", files_metadata=[fm])
        assert len(cfg.files_metadata) == 1
        assert cfg.files_metadata[0].path == "data/docs/hello.txt"
        assert cfg.files_metadata[0].snippet == "Hello world"

    def test_with_chats(self):
        msg = ChatMessage(from_user="alice", to_user="bob", content="Hi!", timestamp="2025-01-01T09:00:00")
        chat = Chat(id="chat1", participants=["alice", "bob"], messages=[msg])
        cfg = TenantConfig(id="t1", chats=[chat])
        assert len(cfg.chats) == 1
        assert cfg.chats[0].id == "chat1"
        assert cfg.chats[0].messages[0].content == "Hi!"

    def test_with_group_chats(self):
        gc = GroupChat(id="gc1", name="team", participants=["alice", "bob", "carol"])
        cfg = TenantConfig(id="t1", group_chats=[gc])
        assert cfg.group_chats[0].name == "team"

    def test_with_meetings(self):
        meeting = Meeting(
            id="m1",
            title="Standup",
            organizer="alice",
            start_time="2025-01-01T09:00:00",
            end_time="2025-01-01T09:30:00",
            agenda="Daily sync",
        )
        cfg = TenantConfig(id="t1", meetings=[meeting])
        assert cfg.meetings[0].title == "Standup"

    def test_with_emails(self):
        email = Email(
            id="e1",
            from_user="alice@example.com",
            to_users=["bob@example.com"],
            subject="Hello",
            body="Hi Bob",
            timestamp="2025-01-01T09:00:00",
        )
        cfg = TenantConfig(id="t1", emails=[email])
        assert cfg.emails[0].subject == "Hello"

    def test_with_channels(self):
        post = ChannelPost(id="p1", author="alice", content="News!", timestamp="2025-01-01T10:00:00")
        channel = Channel(id="ch1", name="announcements", participants=["alice"], posts=[post])
        cfg = TenantConfig(id="t1", channels=[channel])
        assert cfg.channels[0].posts[0].content == "News!"

    def test_resource_limits_default_empty(self):
        cfg = TenantConfig(id="t1")
        assert cfg.resource_limits == {}

    def test_optional_paths_default_none(self):
        cfg = TenantConfig(id="t1")
        assert cfg.data_path is None
        assert cfg.root_path is None


class TestTenantConfigFromYaml:
    """Test TenantConfig.from_yaml classmethod."""

    def test_from_yaml_loads_basic(self, tmp_path):
        tenant_path = _make_tenant_yaml(str(tmp_path))
        cfg = TenantConfig.from_yaml(tenant_path)
        assert cfg.id == "test-tenant"
        assert cfg.domain == "example.com"
        assert len(cfg.users) == 1
        assert cfg.users[0].username == "alice"

    def test_from_yaml_sets_root_path(self, tmp_path):
        tenant_path = _make_tenant_yaml(str(tmp_path))
        cfg = TenantConfig.from_yaml(tenant_path)
        assert cfg.root_path == str(tmp_path)

    def test_from_yaml_sets_data_path_if_dir_exists(self, tmp_path):
        tenant_path = _make_tenant_yaml(str(tmp_path))
        cfg = TenantConfig.from_yaml(tenant_path)
        # _make_tenant_yaml creates the data dir, so data_path should be set
        assert cfg.data_path is not None
        assert cfg.data_path.endswith("data")

    def test_from_yaml_loads_files_config(self, tmp_path):
        tenant_path = _make_tenant_yaml(str(tmp_path))
        files_yaml = [
            {"path": "data/docs/readme.txt", "snippet": "A readme", "created_by": "user1"}
        ]
        config_dir = os.path.join(str(tmp_path), "config")
        with open(os.path.join(config_dir, "files.yaml"), "w") as f:
            yaml_dump(files_yaml, f)
        cfg = TenantConfig.from_yaml(tenant_path)
        assert len(cfg.files_metadata) == 1
        assert cfg.files_metadata[0].snippet == "A readme"

    def test_from_yaml_loads_emails_and_resolves_user_ids(self, tmp_path):
        tenant_path = _make_tenant_yaml(str(tmp_path))
        emails_yaml = [
            {
                "id": "e1",
                "from_user": "user1",
                "to_users": ["user1"],
                "cc_users": [],
                "bcc_users": [],
                "subject": "Test Email",
                "body": "Hello",
                "timestamp": "2025-01-01T09:00:00",
            }
        ]
        config_dir = os.path.join(str(tmp_path), "config")
        with open(os.path.join(config_dir, "emails.yaml"), "w") as f:
            yaml_dump(emails_yaml, f)
        cfg = TenantConfig.from_yaml(tenant_path)
        # user1 should be resolved to alice@example.com
        assert cfg.emails[0].from_user == "alice@example.com"
        assert cfg.emails[0].to_users == ["alice@example.com"]

    def test_from_yaml_loads_chats_config(self, tmp_path):
        tenant_path = _make_tenant_yaml(str(tmp_path))
        chats_yaml = [
            {
                "id": "c1",
                "participants": ["user1"],
                "messages": [
                    {
                        "from_user": "user1",
                        "content": "Hello",
                        "timestamp": "2025-01-01T09:00:00",
                    }
                ],
            }
        ]
        config_dir = os.path.join(str(tmp_path), "config")
        with open(os.path.join(config_dir, "chats.yaml"), "w") as f:
            yaml_dump(chats_yaml, f)
        cfg = TenantConfig.from_yaml(tenant_path)
        assert len(cfg.chats) == 1
        assert cfg.chats[0].messages[0].content == "Hello"

    def test_from_yaml_missing_config_files_returns_empty(self, tmp_path):
        tenant_path = _make_tenant_yaml(str(tmp_path))
        # No config/emails.yaml etc. → all lists should be empty
        cfg = TenantConfig.from_yaml(tenant_path)
        assert cfg.emails == []
        assert cfg.chats == []
        assert cfg.meetings == []


# ---------------------------------------------------------------------------
# AgentConfig tests
# ---------------------------------------------------------------------------


class TestAgentConfigDirect:
    """Test AgentConfig created directly."""

    def test_minimal_construction(self):
        cfg = AgentConfig(
            id="agent1",
            version="1.0",
            model=ModelConfig(provider=ProviderType.OPENAI, name="gpt-4o"),
            system_prompt="You are helpful.",
            tools=ToolConfig(definitions=["read_file"]),
            flow=FlowConfig(strategy=FlowStrategy.REACT),
        )
        assert cfg.id == "agent1"
        assert cfg.flow.max_turns == 10
        assert cfg.tools.definitions == ["read_file"]

    def test_flow_strategies(self):
        for strategy in (FlowStrategy.REACT, FlowStrategy.CHAIN, FlowStrategy.RESEARCHER):
            cfg = AgentConfig(
                id="a",
                version="1",
                model=ModelConfig(provider=ProviderType.AZURE, name="gpt-4"),
                system_prompt="test",
                tools=ToolConfig(definitions=[]),
                flow=FlowConfig(strategy=strategy, max_turns=3),
            )
            assert cfg.flow.strategy == strategy

    def test_optional_embedding_config(self):
        cfg = AgentConfig(
            id="a",
            version="1",
            model=ModelConfig(provider=ProviderType.OPENAI, name="gpt-4o"),
            system_prompt="test",
            tools=ToolConfig(definitions=[]),
            flow=FlowConfig(strategy=FlowStrategy.REACT),
            embedding=EmbeddingConfig(provider=ProviderType.LOCAL, model="all-MiniLM-L6-v2"),
        )
        assert cfg.embedding.model == "all-MiniLM-L6-v2"


class TestAgentConfigFromYaml:
    def test_from_yaml_loads_correctly(self, tmp_path):
        agent_path = _make_agent_yaml(str(tmp_path))
        cfg = AgentConfig.from_yaml(agent_path)
        assert cfg.id == "test-agent"
        assert cfg.model.name == "gpt-4o"
        assert cfg.flow.strategy == FlowStrategy.REACT
        assert cfg.flow.max_turns == 5
        assert "read_file" in cfg.tools.definitions

    def test_from_yaml_defaults(self, tmp_path):
        agent_path = _make_agent_yaml(str(tmp_path))
        cfg = AgentConfig.from_yaml(agent_path)
        assert cfg.embedding is None
        assert cfg.planning_prompt is None
        assert cfg.dynamic_keys == []
