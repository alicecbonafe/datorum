"""Unit tests for CliAppContext helpers that are impractical to exercise
through a full CliRunner invocation:
  - the interactive HITL prompt loop uses click.getchar(), which blocks on
    a real tty and does not cooperate with CliRunner's simulated stdin
    (confirmed by hand: `runner.invoke(..., input="\\r")` hangs rather than
    feeding getchar()). Tested here directly with click.getchar mocked.
  - _split_context_value's branches, exercised directly rather than only
    indirectly through parse_context_bind's regex-gated callers.
"""
import asyncio
from unittest.mock import patch

import pytest

import datorum
import datorum.cli
from datorum.cli.context import CliAppContext


@pytest.fixture
def app_ctx(settings_path):
    return CliAppContext(settings_path=settings_path)


# ==============================================================================
# _split_context_value
# ==============================================================================

class TestSplitContextValue:
    def test_no_colon_returns_none_context(self, app_ctx):
        assert app_ctx._split_context_value("doc1") == (None, "doc1")

    def test_single_context(self, app_ctx):
        assert app_ctx._split_context_value("work:doc1") == ("work", "doc1")

    def test_multiple_contexts_become_a_list(self, app_ctx):
        assert app_ctx._split_context_value("work,other:doc1") == (["work", "other"], "doc1")

    def test_binded_id_itself_can_contain_dots(self, app_ctx):
        assert app_ctx._split_context_value("work:reports.q1.summary.txt") == ("work", "reports.q1.summary.txt")


# ==============================================================================
# parse_context_bind / parse_resource_bind error paths
# ==============================================================================

class TestParseContextBind:
    def test_missing_equals_sign_raises(self, app_ctx):
        with pytest.raises(datorum.DatorumBaseError, match="Invalid --bind-context"):
            app_ctx.parse_context_bind("not-a-valid-binding")

    def test_missing_parenthesized_value_raises(self, app_ctx):
        with pytest.raises(datorum.DatorumBaseError, match="missing '\\(context:binded-id\\)'"):
            app_ctx.parse_context_bind("field=model")

    def test_unknown_bind_type_raises(self, app_ctx):
        with pytest.raises(datorum.DatorumBaseError, match="Unknown context bind type 'not-a-type'"):
            app_ctx.parse_context_bind("field=not-a-type(work:doc1)")

    def test_valid_binding_parses(self, app_ctx):
        bind = app_ctx.parse_context_bind("field=model(work:doc1)")
        assert bind.field_id == "field"
        assert bind.context == "work"
        assert bind.binded_id == "doc1"
        assert bind.context_bind_type == datorum.ContextBindType.model


class TestParseResourceBind:
    def test_missing_equals_sign_raises(self, app_ctx):
        with pytest.raises(datorum.DatorumBaseError, match="Invalid --bind-context"):
            app_ctx.parse_resource_bind("not-a-valid-binding")

    def test_valid_binding_without_selector(self, app_ctx):
        bind = app_ctx.parse_resource_bind("field=factory")
        assert bind.field_id == "field"
        assert bind.factory_name == "factory"
        assert bind.selector is None

    def test_valid_binding_with_selector(self, app_ctx):
        bind = app_ctx.parse_resource_bind("field=factory(selector)")
        assert bind.selector == "selector"


# ==============================================================================
# _catch_updates: the interactive HITL prompt loop
# ==============================================================================

class _FakeBroadcaster:
    """Yields a fixed list of items once, then stops -- mirrors
    Broadcaster.subscribe()'s async-generator contract closely enough for
    _catch_updates, without needing a real Job/Worker run."""

    def __init__(self, items):
        self._items = items

    async def subscribe(self):
        for item in self._items:
            yield item


class _FakeJob:
    def __init__(self, items, context_bindings=()):
        self.update_broadcaster = _FakeBroadcaster(items)
        self.is_streaming = False
        self.context_bindings = list(context_bindings)
        self.resume = lambda: None


class TestCatchUpdatesInteractivePrompt:
    @pytest.mark.asyncio
    async def test_non_interactive_exits_on_pause_without_prompting(self, app_ctx):
        job = _FakeJob(["[working] step 1", "[paused]"])
        with patch("datorum.cli.context.click.getchar") as getchar:
            with pytest.raises(SystemExit) as exc_info:
                await app_ctx._catch_updates(job, exit_on_paused=True)
        assert exc_info.value.code == 0
        getchar.assert_not_called()

    @pytest.mark.asyncio
    async def test_interactive_enter_resumes_the_job(self, app_ctx):
        job = _FakeJob(["[paused]"])
        resumed = []
        job.resume = lambda: resumed.append(True)

        with patch("datorum.cli.context.click.getchar", return_value="\r"):
            await app_ctx._catch_updates(job, exit_on_paused=False)

        assert resumed == [True]

    @pytest.mark.asyncio
    async def test_interactive_escape_exits_without_resuming(self, app_ctx):
        job = _FakeJob(["[paused]"])
        resumed = []
        job.resume = lambda: resumed.append(True)

        with patch("datorum.cli.context.click.getchar", return_value="\x1b"):
            with pytest.raises(SystemExit) as exc_info:
                await app_ctx._catch_updates(job, exit_on_paused=False)

        assert exc_info.value.code == 0
        assert resumed == []

    @pytest.mark.asyncio
    async def test_pause_prints_the_interactive_document_path(self, app_ctx, runner, settings_path):
        """When a context is registered, the paused-prompt path should
        resolve and print the interactive document's real file path."""
        from click.testing import CliRunner
        r = CliRunner().invoke(
            datorum.cli.app, ["-s", str(settings_path), "config", "init", "-c", "contexts", "-f", "flows"],
        )
        assert r.exit_code == 0
        r = CliRunner().invoke(
            datorum.cli.app, ["-s", str(settings_path), "config", "context", "create", "work", "--create-dir"],
        )
        assert r.exit_code == 0
        (settings_path.parent / "contexts" / "work" / "chat.txt").touch()
        r = CliRunner().invoke(
            datorum.cli.app,
            ["-s", str(settings_path), "config", "context", "link", "work",
             str(settings_path.parent / "contexts" / "work" / "chat.txt")],
        )
        assert r.exit_code == 0

        fresh_ctx = CliAppContext(settings_path=settings_path)
        job = _FakeJob(
            ["[paused]"],
            context_bindings=[
                datorum.ContextBind(field_id="interactive", binded_id="chat.txt", context="work"),
            ],
        )

        import io
        import contextlib
        buf = io.StringIO()
        with patch("datorum.cli.context.click.getchar", return_value="\x1b"):
            with contextlib.redirect_stdout(buf):
                with pytest.raises(SystemExit):
                    await fresh_ctx._catch_updates(job, exit_on_paused=False)

        assert "chat.txt" in buf.getvalue()


# ==============================================================================
# _create_binder: explicit api_keys dict branch (default/env-var branch is
# already exercised implicitly by every other CLI test in this suite)
# ==============================================================================

class TestBinderApiKeysFromSettingsDict:
    def test_explicit_api_keys_dict_is_wired_into_the_binder(self, app_ctx, settings_path):
        from datorum.cli.settings import CliAppSettings
        bootstrap = CliAppSettings(api_keys={"MY_PROVIDER_API_KEY": "secret-value"})
        bootstrap.save_as(settings_path)

        binder = app_ctx.binder  # triggers _create_binder, which reloads from settings_path
        factory = binder.factories["api_key"]
        assert factory("MY_PROVIDER_API_KEY") == "secret-value"


# ==============================================================================
# _catch_chunks / _catch_logs / _catch_updates: streaming vs. non-streaming
# ==============================================================================

class TestBroadcastEcho:
    @pytest.mark.asyncio
    async def test_catch_chunks_echoes_without_newlines(self, app_ctx, capsys):
        job = _FakeJob([])
        job.chunk_broadcaster = _FakeBroadcaster(["tok1", "tok2"])
        await app_ctx._catch_chunks(job)
        assert capsys.readouterr().out == "tok1tok2"

    @pytest.mark.asyncio
    async def test_catch_updates_streaming_job_echoes_without_newlines(self, app_ctx, capsys):
        job = _FakeJob(["a", "b"])
        job.is_streaming = True
        await app_ctx._catch_updates(job, exit_on_paused=True)
        assert capsys.readouterr().out == "[UPDATE: a][UPDATE: b]"

    @pytest.mark.asyncio
    async def test_catch_logs_streaming_job_echoes_without_newlines(self, app_ctx, capsys):
        job = _FakeJob([])
        job.log_broadcaster = _FakeBroadcaster(["log1", "log2"])
        job.is_streaming = True
        await app_ctx._catch_logs(job)
        assert capsys.readouterr().out == "[LOG: log1][LOG: log2]"

    @pytest.mark.asyncio
    async def test_catch_logs_non_streaming_job_echoes_one_line_each(self, app_ctx, capsys):
        job = _FakeJob([])
        job.log_broadcaster = _FakeBroadcaster(["log1", "log2"])
        job.is_streaming = False
        await app_ctx._catch_logs(job)
        assert capsys.readouterr().out == "log1\nlog2\n"