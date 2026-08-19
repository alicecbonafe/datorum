

import click

from ..context import CliAppContext
from .base import BaseCommandGroup


class RunGroup(BaseCommandGroup):
    """Group for execution commands."""

    @click.command("pipeline")
    @click.argument("pipeline_id")
    @click.pass_context
    def run_pipeline(ctx: click.Context, pipeline_id: str):
        """Execute a pipeline by ID."""
        app_ctx: CliAppContext = ctx.obj
        # worker = app_ctx.pipeline_worker
        click.echo(f"Running pipeline '{pipeline_id}'")