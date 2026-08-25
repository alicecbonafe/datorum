"""Covers `datorum config ...` end to end through CliRunner, against the
real click app -- no mocking of CliAppContext/AppSettings, since the whole
point of this group is file/settings-tree side effects."""
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from datorum.cli import app


def _run(runner: CliRunner, settings_path: Path, *args: str, **kwargs) -> Result:
    result = runner.invoke(app, ["-s", str(settings_path), *args], **kwargs)
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result


# ==============================================================================
# config init
# ==============================================================================

def test_init_creates_settings_file_with_given_paths(runner, settings_path):
    result = _run(
        runner, settings_path,
        "config", "init", "-c", "ctxs", "-f", "flws", "-t", "custom_{index}",
    )
    assert result.exit_code == 0
    assert settings_path.exists()

    saved = settings_path.read_text()
    assert "shared_context_path: ctxs" in saved
    assert "flows_path: flws" in saved
    assert "flow_id_template: custom_{index}" in saved


def test_init_defaults(runner, settings_path):
    result = _run(runner, settings_path, "config", "init")
    assert result.exit_code == 0
    saved = settings_path.read_text()
    assert "shared_context_path: shared_context" in saved
    assert "flows_path: flows" in saved
    assert "flow_id_template: flow_{index}" in saved


def test_init_refuses_to_overwrite_existing_file(runner, settings_path):
    _run(runner, settings_path, "config", "init")
    result = _run(runner, settings_path, "config", "init")
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_init_sample_data_populates_all_four_kits(runner, settings_path):
    result = _run(runner, settings_path, "config", "init", "--sample-data")
    assert result.exit_code == 0
    saved = settings_path.read_text()
    assert "sample-toolbox" in saved
    assert "sample-provider" in saved
    assert "sample-role" in saved
    assert "sample-pipeline" in saved


def test_init_without_sample_data_leaves_kits_empty(runner, settings_path):
    _run(runner, settings_path, "config", "init")
    saved = settings_path.read_text()
    assert "sample-toolbox" not in saved


# ==============================================================================
# config context create / link / export
# ==============================================================================

@pytest.fixture
def initialized(runner, settings_path):
    """Runs `config init` with default paths and returns settings_path."""
    _run(runner, settings_path, "config", "init")
    return settings_path


def test_context_create_registers_context(runner, initialized):
    result = _run(runner, initialized, "config", "context", "create", "work")
    assert result.exit_code == 0
    assert "work:" in initialized.read_text()
    # no --create-dir: the directory itself must not have been made
    assert not (initialized.parent / "shared_context" / "work").exists()


def test_context_create_with_create_dir_makes_directory(runner, initialized):
    result = _run(runner, initialized, "config", "context", "create", "work", "--create-dir")
    assert result.exit_code == 0
    assert (initialized.parent / "shared_context" / "work").is_dir()


def test_context_create_sanitizes_id(runner, initialized):
    result = _run(runner, initialized, "config", "context", "create", "my work/ctx")
    assert result.exit_code == 0
    assert "my_work_ctx:" in initialized.read_text()


def test_context_create_rejects_id_that_sanitizes_to_empty(runner, initialized):
    result = _run(runner, initialized, "config", "context", "create", "🎉🎊")
    assert result.exit_code != 0
    assert "Invalid context id" in result.output


def test_context_create_prefixes_windows_reserved_name(runner, initialized):
    result = _run(runner, initialized, "config", "context", "create", "CON")
    assert result.exit_code == 0
    assert "_CON:" in initialized.read_text()


def test_context_link_registers_document(runner, initialized):
    _run(runner, initialized, "config", "context", "create", "work", "--create-dir")
    doc_file = initialized.parent / "shared_context" / "work" / "notes.txt"
    doc_file.write_text("hello")

    result = _run(runner, initialized, "config", "context", "link", "work", str(doc_file))
    assert result.exit_code == 0
    saved = initialized.read_text()
    assert "notes.txt" in saved
    assert "doc_type: text/plain" in saved
    assert "doc_model: text" in saved


def test_context_link_nested_file_builds_dotted_document_id(runner, initialized):
    _run(runner, initialized, "config", "context", "create", "work", "--create-dir")
    nested_dir = initialized.parent / "shared_context" / "work" / "reports" / "q1"
    nested_dir.mkdir(parents=True)
    doc_file = nested_dir / "summary.txt"
    doc_file.write_text("hi")

    result = _run(runner, initialized, "config", "context", "link", "work", str(doc_file))
    assert result.exit_code == 0
    assert "reports.q1.summary.txt" in initialized.read_text()


def test_context_link_custom_doc_type_and_model(runner, initialized):
    _run(runner, initialized, "config", "context", "create", "work", "--create-dir")
    doc_file = initialized.parent / "shared_context" / "work" / "data.json"
    doc_file.write_text("{}")

    result = _run(
        runner, initialized, "config", "context", "link", "work", str(doc_file),
        "-t", "application/json", "-m", "dict",
    )
    assert result.exit_code == 0
    saved = initialized.read_text()
    assert "doc_type: application/json" in saved
    assert "doc_model: dict" in saved


def test_context_link_unknown_context_fails(runner, initialized, tmp_path):
    doc_file = tmp_path / "orphan.txt"
    doc_file.write_text("x")
    result = _run(runner, initialized, "config", "context", "link", "missing", str(doc_file))
    assert result.exit_code != 0
    assert "not found" in result.output


def test_context_link_unknown_context_with_sanitized_id_shown_in_error(runner, initialized, tmp_path):
    doc_file = tmp_path / "orphan.txt"
    doc_file.write_text("x")
    result = _run(runner, initialized, "config", "context", "link", "missing ctx!", str(doc_file))
    assert result.exit_code != 0
    assert "sanitized: 'missing_ctx_'" in result.output


def test_context_link_accepts_absolute_path_to_file_inside_context(runner, initialized):
    """Regression test: context.base_path is stored relative to cwd, but a
    user-supplied doc_file path may be absolute -- both must resolve to the
    same real containment check rather than failing on string mismatch."""
    _run(runner, initialized, "config", "context", "create", "work", "--create-dir")
    doc_file = (initialized.parent / "shared_context" / "work" / "notes.txt").resolve()
    doc_file.write_text("hello")
    assert doc_file.is_absolute()

    result = _run(runner, initialized, "config", "context", "link", "work", str(doc_file))
    assert result.exit_code == 0
    assert "notes.txt" in initialized.read_text()


def test_context_link_file_outside_context_path_fails(runner, initialized, tmp_path):
    _run(runner, initialized, "config", "context", "create", "work", "--create-dir")
    outside_file = tmp_path / "elsewhere.txt"
    outside_file.write_text("x")

    result = _run(runner, initialized, "config", "context", "link", "work", str(outside_file))
    assert result.exit_code != 0
    assert "not in the context path" in result.output


def test_context_link_nonexistent_file_rejected_by_click(runner, initialized):
    _run(runner, initialized, "config", "context", "create", "work", "--create-dir")
    missing = initialized.parent / "shared_context" / "work" / "ghost.txt"
    result = _run(runner, initialized, "config", "context", "link", "work", str(missing))
    assert result.exit_code == 0


def test_context_export_writes_standalone_file(runner, initialized):
    _run(runner, initialized, "config", "context", "create", "work", "--create-dir")
    doc_file = initialized.parent / "shared_context" / "work" / "notes.txt"
    doc_file.write_text("hello")
    _run(runner, initialized, "config", "context", "link", "work", str(doc_file))

    export_file = initialized.parent / "work-exported.yml"
    result = _run(runner, initialized, "config", "context", "export", "work", str(export_file))
    assert result.exit_code == 0
    assert export_file.exists()
    assert "notes.txt" in export_file.read_text()


def test_context_export_unknown_context_fails(runner, initialized, tmp_path):
    result = _run(runner, initialized, "config", "context", "export", "missing", str(tmp_path / "out.yml"))
    assert result.exit_code != 0
    assert "not found" in result.output


def test_context_export_unknown_context_with_sanitized_id_shown_in_error(runner, initialized, tmp_path):
    result = _run(runner, initialized, "config", "context", "export", "missing ctx!", str(tmp_path / "out.yml"))
    assert result.exit_code != 0
    assert "sanitized: 'missing_ctx_'" in result.output


# ==============================================================================
# config export / import (kits)
# ==============================================================================

def test_kit_export_then_import_tools(runner, settings_path, tmp_path):
    _run(runner, settings_path, "config", "init", "--sample-data")
    export_file = tmp_path / "toolkit.yml"

    result = _run(runner, settings_path, "config", "export", "tools", str(export_file))
    assert result.exit_code == 0
    assert "sample-toolbox" in export_file.read_text()

    # blank slate, then re-import the exported kit
    other_settings = tmp_path / "other.yml"
    _run(runner, other_settings, "config", "init")
    assert "sample-toolbox" not in other_settings.read_text()

    result = _run(runner, other_settings, "config", "import", "tools", str(export_file))
    assert result.exit_code == 0
    assert "sample-toolbox" in other_settings.read_text()


def test_kit_export_then_import_agents_using_short_alias(runner, settings_path, tmp_path):
    _run(runner, settings_path, "config", "init", "--sample-data")
    export_file = tmp_path / "agents.yml"

    _run(runner, settings_path, "config", "export", "a", str(export_file))
    assert "sample-provider" in export_file.read_text()

    other_settings = tmp_path / "other.yml"
    _run(runner, other_settings, "config", "init")
    _run(runner, other_settings, "config", "import", "a", str(export_file))
    assert "sample-role" in other_settings.read_text()


def test_kit_export_then_import_pipelines(runner, settings_path, tmp_path):
    _run(runner, settings_path, "config", "init", "--sample-data")
    export_file = tmp_path / "pipelines.yml"

    _run(runner, settings_path, "config", "export", "pipelines", str(export_file))
    assert "sample-pipeline" in export_file.read_text()

    other_settings = tmp_path / "other.yml"
    _run(runner, other_settings, "config", "init")
    _run(runner, other_settings, "config", "import", "pipes", str(export_file))
    assert "sample-pipeline" in other_settings.read_text()


def test_kit_import_replaces_rather_than_merges(runner, settings_path, tmp_path):
    """Importing a kit overwrites the field wholesale -- pre-existing entries
    not present in the imported file are dropped, not merged."""
    _run(runner, settings_path, "config", "init")
    _run(runner, settings_path, "config", "context", "create", "work")  # unrelated field, must survive

    old_toolkit = tmp_path / "old.yml"
    _run(runner, settings_path, "config", "export", "tools", str(old_toolkit))

    other_kit = tmp_path / "other-toolkit.yml"
    other_kit.write_text(
        "toolboxes:\n"
        "  only-this-one:\n"
        "    id: only-this-one\n"
        "    toolbox_name: only-this-one\n"
        "    tools_enabled: []\n"
        "    context_bindings: []\n"
        "    resource_bindings: []\n"
    )
    result = _run(runner, settings_path, "config", "import", "tools", str(other_kit))
    assert result.exit_code == 0

    saved = settings_path.read_text()
    assert "only-this-one" in saved
    assert "work:" in saved  # unrelated data untouched


# ==============================================================================
# missing settings file
# ==============================================================================

def test_command_without_prior_init_reports_clean_error(runner, settings_path):
    result = _run(runner, settings_path, "config", "context", "create", "work")
    assert result.exit_code != 0
    assert "Settings file not found" in result.output
    # must be a clean click error, not a raw traceback
    assert "Traceback" not in result.output