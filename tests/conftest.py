from pathlib import Path

import pytest
from click.testing import CliRunner

from datorum.tooling.registry import ToolBoxRegistry, tool, toolbox


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    return tmp_path / "datorum.yml"


@pytest.fixture
def echo_toolbox():
    """Registers a trivial, zero-argument toolbox for the duration of one test."""

    @toolbox(name="echo-toolbox", force=True)
    class EchoToolBox:
        @tool()
        def shout(self) -> str:
            return "HELLO"

    yield "echo-toolbox"
    ToolBoxRegistry.pop("echo-toolbox", None)
