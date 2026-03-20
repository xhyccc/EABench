"""Tests for tool functions in src.core.tools (sandbox tools)."""

import os
import pytest

from src.sandbox.local_sandbox import LocalSandbox


class _MockTenantConfig:
    def __init__(self, data_path=None):
        self.id = "test_tenant"
        self.data_path = data_path


@pytest.fixture()
def sandbox(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sample.txt").write_text("Sample file content", encoding="utf-8")
    (data_dir / "sub").mkdir()
    (data_dir / "sub" / "deep.txt").write_text("Deep content", encoding="utf-8")

    config = _MockTenantConfig(data_path=str(data_dir))
    sb = LocalSandbox(config)
    sb.start()
    yield sb
    sb.stop()


# ---------------------------------------------------------------------------
# read_file tool
# ---------------------------------------------------------------------------


class TestReadFileTool:
    def test_read_file_returns_content(self, sandbox):
        from src.core.tools import read_file

        result = read_file(path="data/sample.txt", sandbox=sandbox)
        assert result == "Sample file content"

    def test_read_file_missing_raises_or_returns_error(self, sandbox):
        from src.core.tools import read_file

        try:
            result = read_file(path="data/missing.txt", sandbox=sandbox)
            # If it doesn't raise, it should at least return a string
            assert isinstance(result, str)
        except FileNotFoundError:
            pass  # acceptable


# ---------------------------------------------------------------------------
# list_files tool
# ---------------------------------------------------------------------------


class TestListFilesTool:
    def test_list_files_root(self, sandbox):
        from src.core.tools import list_files

        result = list_files(path=".", sandbox=sandbox)
        assert "data" in result

    def test_list_files_data_dir(self, sandbox):
        from src.core.tools import list_files

        result = list_files(path="data", sandbox=sandbox)
        assert "sample.txt" in result


# ---------------------------------------------------------------------------
# execute_command tool
# ---------------------------------------------------------------------------


class TestExecuteCommandTool:
    def test_execute_echo(self, sandbox):
        from src.core.tools import execute_command

        result = execute_command(command="echo hi", sandbox=sandbox)
        assert "hi" in result

    def test_execute_returns_string(self, sandbox):
        from src.core.tools import execute_command

        result = execute_command(command="ls", sandbox=sandbox)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# ToolRegistry tests
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_get_schemas_returns_list(self):
        from src.core.tool_registry import registry

        schemas = registry.get_schemas()
        assert isinstance(schemas, list)
        assert len(schemas) > 0

    def test_schema_has_function_name(self):
        from src.core.tool_registry import registry

        schemas = registry.get_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "read_file" in names
        assert "list_files" in names

    def test_get_tool_returns_callable(self):
        from src.core.tool_registry import registry

        tool = registry.get_tool("read_file")
        assert callable(tool)

    def test_get_nonexistent_tool_returns_none(self):
        from src.core.tool_registry import registry

        tool = registry.get_tool("nonexistent_tool_xyz")
        assert tool is None
