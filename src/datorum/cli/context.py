import asyncio
import importlib.util
import re
import sys
from pathlib import Path

import click

import datorum

from .settings import CliAppSettings

_BIND_RE = re.compile(
    r"^(?P<field_id>[^=]+)=(?P<name>[\w\-]+)(?:\((?P<value>[^)]*)\))?$"
)
_ESC_CHAR = "\x1b"
_ENTER_CHAR = "\r"


class BindingSyntaxError(datorum.DatorumBaseError):
    """Raised when a --bind-context / --bind-resource value can't be parsed."""


class CliAppContext:
    def __init__(self, settings_path: Path):
        self.settings = CliAppSettings()
        self.settings.settings_path = settings_path

        self._binder: datorum.Binder | None = None
        self._tool_worker: datorum.ToolWorker | None = None
        self._agent_worker: datorum.AgentWorker | None = None
        self._pipeline_worker: datorum.PipelineWorker | None = None

    @property
    def binder(self):
        if not self._binder:
            self.settings.load_lazy()
            self._create_binder()
        return self._binder

    @property
    def tool_worker(self) -> datorum.ToolWorker:
        if not self._tool_worker:
            self._tool_worker = datorum.ToolWorker(
                binder=self.binder,
                toolkit=self.settings.toolkit,
            )
        return self._tool_worker

    @property
    def agent_worker(self) -> datorum.AgentWorker:
        if not self._agent_worker:
            self._agent_worker = datorum.AgentWorker(
                binder=self.binder,
                agencykit=self.settings.agencykit,
                tool_worker=self.tool_worker,
            )
        return self._agent_worker

    @property
    def pipeline_worker(self) -> datorum.PipelineWorker:
        if not self._pipeline_worker:
            self._pipeline_worker = datorum.PipelineWorker(
                binder=self.binder,
                plumbingkit=self.settings.plumbingkit,
                agent_worker=self.agent_worker,
                tool_worker=self.tool_worker,
            )
            self._pipeline_worker.register_flow_factories(
                flow_path=self.settings.flows_path,
                flow_id_template=self.settings.flow_id_template,
            )
        return self._pipeline_worker

    def load_custom_registry(self):
        if not self.settings.custom_registry:
            return

        base_dir = self.settings.settings_path.parent
        for file_path in self.settings.custom_registry:
            module_key = ".".join([p for p in file_path.parts if "/" not in p])
            module_path = file_path.resolve()
            if not module_path.exists():
                raise click.ClickException(
                    f"Registry file not found: {module_path}"
                )

            module_spec = importlib.util.spec_from_file_location(
                module_path.stem, module_path
            )
            if module_spec is None or module_spec.loader is None:
                raise click.ClickException(
                    f"Failed to load custom registry: {module_path}"
                )
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[module_key] = module
            try:
                module_spec.loader.exec_module(module)
            except Exception as e:
                raise click.ClickException(
                    f"An error occurred while loading custom registry '{module_path}': {e}"
                )

    def parse_context_bind(self, raw: str) -> datorum.ContextBind:
        match = _BIND_RE.match(raw)
        if not match:
            raise BindingSyntaxError(
                f"Invalid --bind-context value '{raw}' (expected 'field=bind-type(context:binded-id)')"
            )
        field_id, type_name, value = match.group("field_id", "name", "value")
        if value is None:
            raise BindingSyntaxError(
                f"Invalid --bind-context value '{raw}': missing '(context:binded-id)'"
            )

        try:
            bind_type = datorum.ContextBindType(type_name)
        except ValueError as exc:
            raise BindingSyntaxError(
                f"Unknown context bind type '{type_name}' in '{raw}'"
            ) from exc

        context, binded_id = self._split_context_value(value)
        return datorum.ContextBind(
            field_id=field_id,
            binded_id=binded_id,
            context=context,
            context_bind_type=bind_type,
        )

    def parse_resource_bind(self, raw: str) -> datorum.ResourceBind:
        match = _BIND_RE.match(raw)
        if not match:
            raise BindingSyntaxError(
                f"Invalid --bind-context value '{raw}' (expected 'field=bind-type(context:binded-id)')"
            )
        field_id, factory_name, selector = match.group("field_id", "name", "value")
        return datorum.ResourceBind(
            field_id=field_id, factory_name=factory_name, selector=selector
        )

    def parse_positional_context(self, raw: str, field_id: str) -> datorum.ContextBind:
        context, binded_id = self._split_context_value(raw)
        return datorum.ContextBind(
            field_id=field_id,
            binded_id=binded_id,
            context=context,
            context_bind_type=datorum.ContextBindType.model,
        )

    def run_job(
        self, worker: datorum.Worker, job: datorum.Job, exit_on_paused: bool = False
    ) -> datorum.Job:
        return asyncio.run(self._run_job_async(worker, job, exit_on_paused))

    def _create_binder(self) -> datorum.Binder:
        self._binder = datorum.Binder()

        for ctx in self.settings.contexts.values():
            self._binder.add_context(context=ctx)

        try:
            datorum.get_resource_factory("api_key")
        except datorum.ResourceFactoryError:
            if self.settings.api_keys is None:
                datorum.register_mapped_api_key_factory(
                    key_name_formatter=lambda k: f"{str.upper(k)}_API_KEY",
                    binder=self._binder,
                )
            else:
                datorum.register_mapped_api_key_factory(
                    self.settings.api_keys,
                    binder=self._binder,
                )

        return self._binder

    def _split_context_value(self, value: str) -> tuple[str | list[str] | None, str]:
        if ":" not in value:
            return None, value
        context_part, binded_id = value.rsplit(":", 1)
        contexts = context_part.split(",")
        return (contexts[0] if len(contexts) == 1 else contexts), binded_id

    async def _run_job_async(
        self, worker: datorum.Worker, job: datorum.Job, exit_on_paused: bool
    ) -> datorum.Job:
        printer = asyncio.create_task(self._gather_catchers(job, exit_on_paused))
        try:
            await worker.run(job)
        finally:
            await printer
        return job

    async def _gather_catchers(self, job: datorum.Job, exit_on_paused: bool) -> None:
        await asyncio.gather(
            self._catch_chunks(job),
            self._catch_updates(job, exit_on_paused),
            self._catch_logs(job),
        )

    async def _catch_chunks(self, job: datorum.Job) -> None:
        async for item in job.chunk_broadcaster.subscribe():
            click.echo(item, nl=False)

    async def _catch_updates(self, job: datorum.Job, exit_on_paused: bool) -> None:
        async for item in job.update_broadcaster.subscribe():
            if job.is_streaming:
                click.echo(f"[UPDATE: {item}]", nl=False)
            else:
                click.echo(f"[UPDATE] {item}")

            if item == f"[{datorum.JobStatus.PAUSED.value.lower()}]":
                for bind in job.context_bindings:
                    if bind.field_id == "interactive":
                        interactive = await self.binder.find_document(
                            bind.binded_id, bind.context
                        )
                        click.echo(
                            f"Please edit the file before resuming: '{interactive.doc_path}'"
                        )
                        break

                if exit_on_paused:
                    click.echo("Job has pause, exiting.")
                    sys.exit(0)
                else:
                    click.echo("Job has paused, press ENTER to resume or ESC to exit.")
                    while True:
                        key = click.getchar()
                        if key == _ESC_CHAR:
                            click.echo("Exiting.")
                            sys.exit(0)
                        elif key == _ENTER_CHAR:
                            click.echo("Resuming...")
                            job.resume()
                            break

    async def _catch_logs(self, job: datorum.Job) -> None:
        async for item in job.log_broadcaster.subscribe():
            if job.is_streaming:
                click.echo(f"[LOG: {item}]", nl=False)
            else:
                click.echo(item)
