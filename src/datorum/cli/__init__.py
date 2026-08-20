from pathlib import Path

import click

from .commands.config import ConfigGroup
from .commands.run import RunGroup
from .context import CliAppContext


@click.group()
@click.option(
    "-s",
    "--settings",
    "settings_path",
    type=click.Path(path_type=Path),
    default=Path(".datorum.yml"),
    show_default=True,
    help="Path to the datorum settings file.",
)
@click.pass_context
def app(ctx: click.Context, settings_path: Path) -> None:
    ctx.obj = CliAppContext(settings_path=settings_path)


app.add_command(ConfigGroup(name="config", help="Manage CLI settings file."))
app.add_command(RunGroup(name="run", help="Run tools, agents and pipelines."))
