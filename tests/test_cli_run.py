"""Covers `datorum run ...` end to end through CliRunner. run_tool and
run_pipeline get full happy-path coverage using a real in-process toolbox
fixture; run_agent is covered on its argument-parsing/error paths only,
since a real run needs a live inference endpoint."""
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from datorum.cli import app


def _run(runner: CliRunner, settings_path: Path, *args: str, **kwargs) -> Result:
    result = runner.invoke(app, ["-s", str(settings_path), *args], **kwargs)
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result


@pytest.fixture
def workspace(runner, settings_path):
    """Settings file + contexts_path/flows_path all rooted under one cwd
    (settings_path already chdir's there -- see conftest.py)."""
    _run(runner, settings_path, "config", "init", "-c", "contexts", "-f", "flows")
    return settings_path


@pytest.fixture
def linked_context(runner, workspace):
    """A context named 'work' with params.txt/result.txt/chat.txt already
    linked as text/plain documents, ready to bind against."""
    _run(runner, workspace, "config", "context", "create", "work", "--create-dir")
    base = workspace.parent / "contexts" / "work"
    for name in ("params.txt", "result.txt", "chat.txt"):
        (base / name).touch()
        _run(runner, workspace, "config", "context", "link", "work", str(base / name))
    return workspace


@pytest.fixture
def echo_tool_enabled(runner, linked_context, echo_toolbox):
    """echo_toolbox registered in-process, and wired into the settings file
    with the tool enabled, ready for `run tool`."""
    kit_file = linked_context.parent / "echo-toolkit.yml"
    kit_file.write_text(
        "toolboxes:\n"
        f"  {echo_toolbox}:\n"
        f"    id: {echo_toolbox}\n"
        f"    toolbox_name: {echo_toolbox}\n"
        "    tools_enabled: [shout]\n"
        "    context_bindings: []\n"
        "    resource_bindings: []\n"
    )
    _run(runner, linked_context, "config", "import", "tools", str(kit_file))
    return linked_context


# ==============================================================================
# run tool
# ==============================================================================

def test_run_tool_writes_result_and_leaves_params_untouched(runner, echo_tool_enabled, echo_toolbox):
    base = echo_tool_enabled.parent / "contexts" / "work"
    (base / "params.txt").write_text("original params")

    result = _run(runner, echo_tool_enabled, "run", "tool", f"{echo_toolbox}.shout", "params.txt", "result.txt")
    assert result.exit_code == 0
    assert (base / "result.txt").read_text() == "HELLO"
    assert (base / "params.txt").read_text() == "original params"


def test_run_tool_unknown_toolbox_reports_clean_error(runner, linked_context):
    result = _run(runner, linked_context, "run", "tool", "no-such-toolbox.shout", "params.txt", "result.txt")
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_run_tool_disabled_tool_reports_clean_error(runner, linked_context, echo_toolbox):
    kit_file = linked_context.parent / "echo-toolkit.yml"
    kit_file.write_text(
        "toolboxes:\n"
        f"  {echo_toolbox}:\n"
        f"    id: {echo_toolbox}\n"
        f"    toolbox_name: {echo_toolbox}\n"
        "    tools_enabled: []\n"  # shout not enabled
        "    context_bindings: []\n"
        "    resource_bindings: []\n"
    )
    _run(runner, linked_context, "config", "import", "tools", str(kit_file))

    result = _run(runner, linked_context, "run", "tool", f"{echo_toolbox}.shout", "params.txt", "result.txt")
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_run_tool_accepts_bind_context_option(runner, echo_tool_enabled, echo_toolbox):
    """-c/--bind-context is threaded through and parses without error, even
    though this particular tool never reads the extra binding."""
    result = _run(
        runner, echo_tool_enabled, "run", "tool", f"{echo_toolbox}.shout", "params.txt", "result.txt",
        "-c", "extra=model(work:chat.txt)",
    )
    assert result.exit_code == 0


def test_run_tool_malformed_bind_context_reports_clean_error(runner, echo_tool_enabled, echo_toolbox):
    result = _run(
        runner, echo_tool_enabled, "run", "tool", f"{echo_toolbox}.shout", "params.txt", "result.txt",
        "-c", "not-a-valid-binding",
    )
    assert result.exit_code != 0
    assert "Traceback" not in result.output


# ==============================================================================
# run agent -- argument parsing and error paths only (no live LLM here)
# ==============================================================================

def test_run_agent_unknown_role_reports_clean_error(runner, linked_context):
    result = _run(runner, linked_context, "run", "agent", "no-such-role", "chat.txt")
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_run_agent_with_explicit_provider_still_fails_cleanly_when_unknown(runner, linked_context):
    result = _run(runner, linked_context, "run", "agent", "no-such-role", "chat.txt", "-p", "no-such-provider")
    assert result.exit_code != 0
    assert "Traceback" not in result.output


# ==============================================================================
# run pipeline
# ==============================================================================

@pytest.fixture
def hitl_pipeline_kit(linked_context):
    pipeline_file = linked_context.parent / "pipeline.yml"
    pipeline_file.write_text(
        "pipelines:\n"
        "  hitl-pipe:\n"
        "    id: hitl-pipe\n"
        '    first_step_id: "in"\n'
        "    steps:\n"
        "      in:\n"
        "        type: human\n"
        '        id: "in"\n'
        "        target_id: null\n"
        "        interactive_document_id: chat.txt\n"
        "        interactive_document_context: work\n"
    )
    return pipeline_file


def test_run_pipeline_requires_exactly_one_of_flow_id_or_pipeline(runner, linked_context):
    result = _run(runner, linked_context, "run", "pipeline")
    assert result.exit_code != 0
    assert "Provide either FLOW_ID" in result.output


def test_run_pipeline_rejects_both_flow_id_and_pipeline(runner, linked_context):
    result = _run(runner, linked_context, "run", "pipeline", "flow_0", "-p", "some-pipeline")
    assert result.exit_code != 0
    assert "Provide either FLOW_ID" in result.output


def test_run_pipeline_create_only_writes_flow_file_without_running(runner, linked_context, hitl_pipeline_kit):
    _run(runner, linked_context, "config", "import", "pipelines", str(hitl_pipeline_kit))

    result = _run(runner, linked_context, "run", "pipeline", "-p", "hitl-pipe", "--create-only")
    assert result.exit_code == 0

    flow_file = linked_context.parent / "flows" / "flow_0.yml"
    assert flow_file.exists()
    assert "state: paused" not in flow_file.read_text()  # never actually run


def test_run_pipeline_resume_in_fresh_invocation_pauses_and_exits_non_interactive(
    runner, linked_context, hitl_pipeline_kit,
):
    """Regression test: resuming a flow must go through pipeline_worker
    (which registers the pipeflow resource factories), not app_ctx.binder
    directly -- and a fresh CLI invocation is a fresh CliAppContext, so this
    only fails if that wiring is broken."""
    _run(runner, linked_context, "config", "import", "pipelines", str(hitl_pipeline_kit))
    _run(runner, linked_context, "run", "pipeline", "-p", "hitl-pipe", "--create-only")

    result = _run(runner, linked_context, "run", "pipeline", "flow_0", "--non-interactive")
    assert result.exit_code == 0

    flow_file = linked_context.parent / "flows" / "flow_0.yml"
    assert "state: paused" in flow_file.read_text()


def test_run_pipeline_unknown_flow_id_reports_clean_error(runner, linked_context):
    result = _run(runner, linked_context, "run", "pipeline", "no-such-flow", "--non-interactive")
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_run_pipeline_unknown_pipeline_id_reports_clean_error(runner, linked_context):
    result = _run(runner, linked_context, "run", "pipeline", "-p", "no-such-pipeline")
    assert result.exit_code != 0
    assert "Traceback" not in result.output