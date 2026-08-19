from pathlib import Path
from typing import Callable

import click

import datorum

from ..context import CliAppContext
from .base import BaseCommandGroup, cli_command



_KIT_ALIASES: dict[str, str] = {
    "tools": "toolkit",
    "t": "toolkit",
    "agents": "agencykit",
    "a": "agencykit",
    "pipelines": "plumbingkit",
    "pipes": "plumbingkit",
    "p": "plumbingkit",
}
_KIT_LOADERS: dict[str, Callable] = {
    "toolkit": datorum.ToolKit.load,
    "agencykit": datorum.AgencyKit.load,
    "plumbingkit": datorum.PlumbingKit.load,
}

class ConfigGroup(BaseCommandGroup):
    """Group for configuration commands."""

    @staticmethod
    @cli_command("init", load_settings=False)
    @click.option("-c", "--contexts", "contexts_path", type=click.Path(path_type=Path), default=Path("contexts"), show_default=True)
    @click.option("-f", "--flows", "flows_path", type=click.Path(path_type=Path), default=Path("flows"), show_default=True)
    @click.option("-t", "--flow-id-template", "flow_id_template", default="flow_{index}", show_default=True)
    @click.option("-d", "--sample-data", "sample_data", is_flag=True)
    @click.pass_obj
    def init_config(
        app_ctx: CliAppContext,
        contexts_path: Path,
        flows_path: Path,
        flow_id_template: str,
        sample_data: bool):
        """Initialize the app configuration."""
        if app_ctx.settings.settings_path.exists():
            raise click.ClickException(f"Settings file already exists: '{app_ctx.settings.settings_path}'")

        click.echo(f"Initializing config at {app_ctx.settings.settings_path}...")
        app_ctx.settings.contexts_path = contexts_path
        app_ctx.settings.flows_path = flows_path
        app_ctx.settings.flow_id_template = flow_id_template

        if sample_data:
            app_ctx.settings.toolkit.toolboxes["sample-toolbox"] = datorum.ToolBoxSetUp(
                id="sample-toolbox",
                toolbox_name="",
            )
            app_ctx.settings.agencykit.providers["sample-provider"] = datorum.InferenceServiceProvider(
                id="sample-provider",
                description="Change me",
                base_url="http://localhost/api/v1/",
                api_key_selector="local",
            )
            app_ctx.settings.agencykit.roles["sample-role"] = datorum.AgentRole(
                id="sample-role",
                description="Change me",
            )
            app_ctx.settings.plumbingkit.pipelines["sample-pipeline"] = datorum.Pipeline(
                id="sample-pipeline",
                description="Change me",

            )

        app_ctx.settings.save()

        click.echo("Done!")

    @staticmethod
    @cli_command("export")
    @click.argument("kit_type")
    @click.argument("output_file", type=click.Path(path_type=Path))
    @click.pass_obj
    def export_kit(
        app_ctx: CliAppContext,
        kit_type: str,
        output_file: Path,
    ):
        click.echo(f"Exporting {kit_type} to {output_file}...")
        kit_name = _KIT_ALIASES.get(kit_type, kit_type)
        kit = getattr(app_ctx.settings, kit_name)
        kit.save_as(output_file)
        click.echo("Done!")

    @staticmethod
    @cli_command("import")
    @click.argument("kit_type")
    @click.argument("input_file", type=click.Path(exists=True, path_type=Path))
    @click.pass_obj
    def import_kit(
        app_ctx: CliAppContext,
        kit_type: str,
        input_file: Path,
    ):
        click.echo(f"Importing {kit_type} from {input_file}...")
        kit_name = _KIT_ALIASES.get(kit_type, kit_type)
        kit = _KIT_LOADERS[kit_name](input_file)
        setattr(app_ctx.settings, kit_name, kit)
        app_ctx.settings.save()
        click.echo("Done!")

