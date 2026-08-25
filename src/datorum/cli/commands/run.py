import click
from datetime import datetime

import datorum

from ..context import CliAppContext
from .base import BaseCommandGroup, cli_command


class RunGroup(BaseCommandGroup):
    """Group for execution commands."""

    @staticmethod
    @cli_command("tool")
    @click.argument("selector")
    @click.argument("params", metavar="[CONTEXT:]DOCUMENT_ID")
    @click.argument("result", metavar="[CONTEXT:]DOCUMENT_ID")
    @click.option(
        "-c",
        "--bind-context",
        "context_binds",
        multiple=True,
        metavar="FIELD=TYPE([CONTEXT:]ID)",
    )
    @click.option(
        "-r",
        "--bind-resource",
        "resource_binds",
        multiple=True,
        metavar="FIELD=FACTORY(SELECTOR)",
    )
    @click.pass_obj
    def run_tool(
        app_ctx: CliAppContext,
        selector: str,
        params: str,
        result: str,
        context_binds: list[str],
        resource_binds: list[str],
    ):
        job = datorum.Job(
            id=f"tool_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}",
            context_bindings=[
                app_ctx.parse_positional_context(params, field_id="tool_params"),
                app_ctx.parse_positional_context(result, field_id="tool_result"),
                *(app_ctx.parse_context_bind(b) for b in context_binds),
            ],
            resource_bindings=[
                datorum.ResourceBind(
                    field_id="toolbox_setup",
                    factory_name="toolbox_setup",
                    selector=selector,
                ),
                *(app_ctx.parse_resource_bind(b) for b in resource_binds),
            ],
        )
        app_ctx.run_job(app_ctx.tool_worker, job)

    @staticmethod
    @cli_command("agent")
    @click.argument("role")
    @click.argument("chat_history", metavar="[CONTEXT:]DOCUMENT_ID")
    @click.option(
        "-p",
        "--provider",
        "provider",
        default=None,
        help="Inferenceprovider ID. Omit to find by role's preferred models.",
    )
    @click.option(
        "-c",
        "--bind-context",
        "context_binds",
        multiple=True,
        metavar="FIELD=TYPE([CONTEXT:]ID)",
    )
    @click.option(
        "-r",
        "--bind-resource",
        "resource_binds",
        multiple=True,
        metavar="FIELD=FACTORY(SELECTOR)",
    )
    @click.pass_obj
    def run_agent(
        app_ctx: CliAppContext,
        role: str,
        chat_history: str,
        provider: str | None,
        context_binds: list[str],
        resource_binds: list[str],
    ):
        """Run one agent turn against CHAT_HISTORY."""
        resource_bindings = [
            datorum.ResourceBind(
                field_id="agent_role",
                factory_name="agent_role",
                selector=role,
            ),
            *(app_ctx.parse_resource_bind(b) for b in resource_binds),
        ]
        if provider:
            resource_bindings.append(
                datorum.ResourceBind(
                    field_id="inference_provider",
                    factory_name="inference_provider",
                    selector=provider,
                )
            )

        job = datorum.Job(
            id=f"agent_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}",
            context_bindings=[
                app_ctx.parse_positional_context(chat_history, field_id="chat_history"),
                *(app_ctx.parse_context_bind(b) for b in context_binds),
            ],
            resource_bindings=resource_bindings,
        )

        app_ctx.run_job(app_ctx.agent_worker, job)

    @staticmethod
    @cli_command("pipeline")
    @click.argument("flow_id", required=False)
    @click.option(
        "-p", "--pipeline", "pipeline_id", help="Pipeline ID to start a new flow from."
    )
    @click.option(
        "-c",
        "--create-only",
        "create_only",
        is_flag=True,
        help="Create the flow file and exit without running it.",
    )
    @click.option("--non-interactive", "non_interactive", is_flag=True, help="")
    @click.pass_obj
    def run_pipeline(
        app_ctx: CliAppContext,
        flow_id: str | None,
        pipeline_id: str | None,
        create_only: bool,
        non_interactive: bool,
    ):
        """Start a new flow (-p/--pipeline) or result an existing one (FLOW_ID)."""
        if bool(flow_id) == bool(pipeline_id):
            raise click.UsageError(
                "Provide either FLOW_ID (to result) or -p/--pipeline (to start), not both."
            )

        if pipeline_id:
            pipeflow = app_ctx.pipeline_worker.create_flow(pipeline_id)
            click.echo(f"Created flow '{pipeflow.id}' at '{pipeflow.settings_path}'")
        else:
            pipeflow = app_ctx.pipeline_worker.binder.load_resource(
                datorum.ResourceBind(
                    field_id="pipeflow",
                    factory_name="restore_pipeflow",
                    selector=flow_id,
                )
            )

        if create_only:
            return

        job = datorum.Job(
            id=pipeflow.id,
            resource_bindings=[
                datorum.ResourceBind(
                    field_id="pipeflow",
                    factory_name="restore_pipeflow",
                    selector=pipeflow.id,
                )
            ],
        )
        app_ctx.run_job(app_ctx.pipeline_worker, job, exit_on_paused=non_interactive)
