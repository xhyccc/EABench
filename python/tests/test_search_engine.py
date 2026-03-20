"""Tests for src.core.search_engine.SearchEngine (using MockEmbeddingProvider)."""

import asyncio
import os
import pytest

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
from src.core.embedding_provider import MockEmbeddingProvider
from src.core.search_engine import SearchEngine
from src.sandbox.local_sandbox import LocalSandbox


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(uid: str, username: str, email: str, display: str) -> UserInfo:
    return UserInfo(
        id=uid,
        username=username,
        profile=UserProfile(
            email=email,
            name=UserName(display_name=display, first_name=display.split()[0], last_name=display.split()[-1]),
        ),
    )


def _make_tenant() -> TenantConfig:
    users = [
        _make_user("u1", "alice", "alice@example.com", "Alice Smith"),
        _make_user("u2", "bob", "bob@example.com", "Bob Jones"),
    ]
    files = [
        FileMetadata(path="data/docs/report.txt", created_by="u1", snippet="Quarterly earnings report"),
        FileMetadata(path="data/notes/meeting.txt", snippet="Team meeting notes"),
    ]
    chats = [
        Chat(
            id="c1",
            participants=["u1", "u2"],
            messages=[
                ChatMessage(from_user="u1", to_user="u2", content="Hey Bob!", timestamp="2025-01-01T09:00:00"),
                ChatMessage(from_user="u2", to_user="u1", content="Hi Alice!", timestamp="2025-01-01T09:01:00"),
            ],
        )
    ]
    emails = [
        Email(
            id="e1",
            from_user="alice@example.com",
            to_users=["bob@example.com"],
            subject="Budget Review",
            body="Please review the Q4 budget.",
            timestamp="2025-01-01T10:00:00",
        )
    ]
    meetings = [
        Meeting(
            id="m1",
            title="Sprint Planning",
            organizer="u1",
            start_time="2025-01-02T09:00:00",
            end_time="2025-01-02T10:00:00",
            agenda="Plan the sprint",
            transcript="Alice: Let's plan our sprint...",
        )
    ]
    group_chats = [
        GroupChat(
            id="gc1",
            name="Engineering",
            participants=["u1", "u2"],
            messages=[
                ChatMessage(from_user="u1", content="Build is green!", timestamp="2025-01-01T11:00:00"),
            ],
        )
    ]
    channels = [
        Channel(
            id="ch1",
            name="announcements",
            participants=["u1", "u2"],
            posts=[
                ChannelPost(id="p1", author="u1", content="New release available!", timestamp="2025-01-01T12:00:00"),
            ],
        )
    ]
    return TenantConfig(
        id="test",
        domain="example.com",
        users=users,
        files_metadata=files,
        chats=chats,
        emails=emails,
        meetings=meetings,
        group_chats=group_chats,
        channels=channels,
    )


class _MockSandbox:
    """Minimal sandbox that returns empty data (search engine uses it for file content)."""

    def list_files(self, path):
        return []

    def read_file(self, path):
        raise FileNotFoundError(path)


@pytest.fixture()
def tenant():
    return _make_tenant()


@pytest.fixture()
def engine(tenant):
    emb = MockEmbeddingProvider()
    sb = _MockSandbox()
    return SearchEngine(tenant_config=tenant, embedding_provider=emb, sandbox=sb)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchEngineIndexing:
    """Tests for the index_all method."""

    def test_index_all_runs_without_error(self, engine):
        asyncio.run(engine.index_all())
        # Indices should be populated after indexing
        assert len(engine.indices["file_snippets"]["data"]) > 0

    def test_file_snippets_indexed(self, engine):
        asyncio.run(engine.index_all())
        paths = [d["path"] for d in engine.indices["file_snippets"]["data"]]
        assert any("report.txt" in p for p in paths)

    def test_users_indexed(self, engine):
        asyncio.run(engine.index_all())
        assert len(engine.indices["users"]["data"]) == 2

    def test_emails_indexed(self, engine):
        asyncio.run(engine.index_all())
        subjects = [d["subject"] for d in engine.indices["emails"]["data"]]
        assert "Budget Review" in subjects

    def test_chats_indexed(self, engine):
        asyncio.run(engine.index_all())
        assert len(engine.indices["chats"]["data"]) > 0

    def test_meetings_indexed(self, engine):
        asyncio.run(engine.index_all())
        titles = [d.get("title", "") for d in engine.indices["meetings_config"]["data"]]
        assert "Sprint Planning" in titles

    def test_group_chats_indexed(self, engine):
        asyncio.run(engine.index_all())
        assert len(engine.indices["group_chats"]["data"]) > 0

    def test_channels_indexed(self, engine):
        asyncio.run(engine.index_all())
        assert len(engine.indices["channels"]["data"]) > 0


class TestSearchEngineUserContext:
    def test_set_user_context_populates_emails(self, engine):
        engine.set_user_context("u1")
        assert engine.current_user_id == "u1"
        # alice@example.com should be in the user emails list
        assert "alice@example.com" in engine.current_user_emails

    def test_set_user_context_unknown_user(self, engine):
        engine.set_user_context("unknown_user")
        assert engine.current_user_id == "unknown_user"
        assert engine.current_user_emails == []


class TestSearchEngineSearch:
    """Tests for the search methods (returns ranked results)."""

    def test_search_files_returns_results(self, engine):
        asyncio.run(engine.index_all())
        results = asyncio.run(engine.search("file_snippets", "quarterly report", top_k=2))
        assert isinstance(results, list)

    def test_search_emails_returns_results(self, engine):
        asyncio.run(engine.index_all())
        results = asyncio.run(engine.search("emails", "budget", top_k=2))
        assert isinstance(results, list)

    def test_search_people_returns_results(self, engine):
        asyncio.run(engine.index_all())
        results = asyncio.run(engine.search("users", "Alice Smith", top_k=2))
        assert isinstance(results, list)

    def test_search_chats_returns_results(self, engine):
        asyncio.run(engine.index_all())
        results = asyncio.run(engine.search("chats", "Hey Bob", top_k=2))
        assert isinstance(results, list)

    def test_search_meetings_returns_results(self, engine):
        asyncio.run(engine.index_all())
        results = asyncio.run(engine.search("meetings_config", "sprint planning", top_k=2))
        assert isinstance(results, list)

    def test_top_k_limits_results(self, engine):
        asyncio.run(engine.index_all())
        results = asyncio.run(engine.search("file_snippets", "report", top_k=1))
        assert len(results) <= 1

    def test_search_returns_list_even_on_empty_index(self, tenant):
        emb = MockEmbeddingProvider()
        sb = _MockSandbox()
        empty_engine = SearchEngine(
            tenant_config=TenantConfig(id="empty"),
            embedding_provider=emb,
            sandbox=sb,
        )
        # Don't call index_all – indices are empty
        results = asyncio.run(empty_engine.search("file_snippets", "anything", top_k=5))
        assert results == []
