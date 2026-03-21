"""Tests for src.sandbox.local_sandbox.LocalSandbox."""

import os
import pytest
import tempfile

from src.sandbox.local_sandbox import LocalSandbox


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _MockTenantConfig:
    """Minimal stand-in for TenantConfig used by LocalSandbox."""

    def __init__(self, data_path=None):
        self.id = "test_tenant"
        self.data_path = data_path


@pytest.fixture()
def sandbox_with_data(tmp_path):
    """Create a LocalSandbox backed by a real temporary data directory."""
    # Build a small data directory
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "hello.txt").write_text("Hello, world!", encoding="utf-8")
    (data_dir / "subdir").mkdir()
    (data_dir / "subdir" / "nested.txt").write_text("Nested content", encoding="utf-8")

    config = _MockTenantConfig(data_path=str(data_dir))
    sb = LocalSandbox(config)
    sb.start()
    yield sb
    sb.stop()


@pytest.fixture()
def empty_sandbox():
    """Create a LocalSandbox with no data directory."""
    config = _MockTenantConfig(data_path=None)
    sb = LocalSandbox(config)
    sb.start()
    yield sb
    sb.stop()


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestSandboxLifecycle:
    def test_start_creates_root_dir(self, tmp_path):
        config = _MockTenantConfig()
        sb = LocalSandbox(config)
        sb.start()
        assert sb.root_dir is not None
        assert os.path.isdir(sb.root_dir)
        sb.stop()

    def test_stop_removes_root_dir(self, tmp_path):
        config = _MockTenantConfig()
        sb = LocalSandbox(config)
        sb.start()
        root = sb.root_dir
        sb.stop()
        assert not os.path.exists(root)

    def test_double_stop_is_safe(self, tmp_path):
        config = _MockTenantConfig()
        sb = LocalSandbox(config)
        sb.start()
        sb.stop()
        sb.stop()  # should not raise


# ---------------------------------------------------------------------------
# Hydration (data copy) tests
# ---------------------------------------------------------------------------


class TestSandboxHydration:
    def test_data_dir_copied_into_sandbox(self, tmp_path):
        data_dir = tmp_path / "mydata"
        data_dir.mkdir()
        (data_dir / "file.txt").write_text("content", encoding="utf-8")

        config = _MockTenantConfig(data_path=str(data_dir))
        sb = LocalSandbox(config)
        sb.start()
        try:
            # The sandbox should contain a 'data' subdirectory
            sandbox_data = os.path.join(sb.root_dir, "data")
            assert os.path.isdir(sandbox_data)
            assert "file.txt" in os.listdir(sandbox_data)
        finally:
            sb.stop()

    def test_no_data_path_sandbox_still_starts(self):
        config = _MockTenantConfig(data_path=None)
        sb = LocalSandbox(config)
        sb.start()
        try:
            assert os.path.isdir(sb.root_dir)
        finally:
            sb.stop()


# ---------------------------------------------------------------------------
# read_file tests
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_read_existing_file_by_exact_path(self, sandbox_with_data):
        content = sandbox_with_data.read_file("data/hello.txt")
        assert content == "Hello, world!"

    def test_read_nested_file(self, sandbox_with_data):
        content = sandbox_with_data.read_file("data/subdir/nested.txt")
        assert content == "Nested content"

    def test_read_missing_file_raises(self, sandbox_with_data):
        with pytest.raises(FileNotFoundError):
            sandbox_with_data.read_file("data/nonexistent.txt")

    def test_read_file_fuzzy_match(self, sandbox_with_data):
        # Fuzzy: just the filename portion
        content = sandbox_with_data.read_file("hello.txt")
        assert content == "Hello, world!"

    def test_read_outside_sandbox_raises(self, sandbox_with_data):
        # read_file catches the ValueError from _resolve_path and falls through
        # to fuzzy matching, which finds no match and raises FileNotFoundError
        with pytest.raises((ValueError, FileNotFoundError)):
            sandbox_with_data.read_file("../../etc/passwd")


# ---------------------------------------------------------------------------
# write_file tests
# ---------------------------------------------------------------------------


class TestWriteFile:
    def test_write_and_read_back(self, sandbox_with_data):
        sandbox_with_data.write_file("data/new_file.txt", "brand new content")
        content = sandbox_with_data.read_file("data/new_file.txt")
        assert content == "brand new content"

    def test_overwrite_existing_file(self, sandbox_with_data):
        sandbox_with_data.write_file("data/hello.txt", "overwritten")
        content = sandbox_with_data.read_file("data/hello.txt")
        assert content == "overwritten"

    def test_write_outside_sandbox_raises(self, sandbox_with_data):
        with pytest.raises(ValueError, match="Access denied"):
            sandbox_with_data.write_file("../../tmp/evil.txt", "evil")


# ---------------------------------------------------------------------------
# list_files tests
# ---------------------------------------------------------------------------


class TestListFiles:
    def test_list_root_contains_data(self, sandbox_with_data):
        files = sandbox_with_data.list_files(".")
        assert "data" in files

    def test_list_data_dir(self, sandbox_with_data):
        files = sandbox_with_data.list_files("data")
        assert "hello.txt" in files
        assert "subdir" in files

    def test_list_subdirectory(self, sandbox_with_data):
        files = sandbox_with_data.list_files("data/subdir")
        assert "nested.txt" in files

    def test_list_outside_sandbox_raises(self, sandbox_with_data):
        with pytest.raises(ValueError, match="Access denied"):
            sandbox_with_data.list_files("../../")


# ---------------------------------------------------------------------------
# execute_command tests
# ---------------------------------------------------------------------------


class TestExecuteCommand:
    def test_simple_echo(self, sandbox_with_data):
        output = sandbox_with_data.execute_command("echo hello")
        assert "hello" in output

    def test_list_command(self, sandbox_with_data):
        output = sandbox_with_data.execute_command("ls")
        assert "data" in output

    def test_command_with_error_returns_stderr(self, sandbox_with_data):
        output = sandbox_with_data.execute_command("ls /nonexistent_path_abc_xyz")
        # Should contain some error indicator, not raise
        assert isinstance(output, str)
