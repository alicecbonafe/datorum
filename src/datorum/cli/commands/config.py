from pathlib import Path
import re
from typing import Callable
import unicodedata

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


def _sanitize_id(id) -> str | None:
    id = unicodedata.normalize('NFKD', id).encode('ascii', 'ignore').decode('ascii')
    id = re.sub(r"[^\w\-.]", "_", id)
    id = re.sub(r"_+", "_", id)
    if not id:
        return None

    windows_compatibility_reserved = {
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5',
        'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5',
        'LPT6', 'LPT7', 'LPT8', 'LPT9'
    }
    if id.upper() in windows_compatibility_reserved:
        id = '_' + id
    id = id.rstrip(' .')
    return id


class ContextGroup(BaseCommandGroup):
    """Group for document context commands."""

    @staticmethod
    @cli_command("create")
    @click.argument("context_id")
    @click.option("-c", "--create-dir", "create_dir", is_flag=True)
    @click.pass_obj
    def create_context(
        app_ctx: CliAppContext,
        context_id: str,
        create_dir: bool,
    ):
        sanitized_id = _sanitize_id(context_id)
        if not sanitized_id:
            raise click.ClickException(f"Invalid context id: '{context_id}'")

        context = datorum.DocumentContext(id=context_id)
        context.base_path = app_ctx.settings.contexts_path / sanitized_id
        if create_dir:
            context.base_path.mkdir(parents=True, exist_ok=True)

        app_ctx.settings.contexts[sanitized_id] = context
        app_ctx.settings.save()

    @staticmethod
    @cli_command("link")
    @click.argument("context_id")
    @click.argument("doc_file", type=click.Path(exists=True, path_type=Path))
    @click.option("-t", "--doc-type", "doc_type", default="text/plain", show_default=True)
    @click.option("-m", "--doc-model", "doc_model", default="text", show_default=True)
    @click.pass_obj
    def link_document(
        app_ctx: CliAppContext,
        context_id: str,
        doc_file: Path,
        doc_type: str,
        doc_model: str,
    ):
        click.echo(f"Linking document '{doc_file}' to context '{context_id}'...")

        sanitized_id = _sanitize_id(context_id)
        if sanitized_id not in app_ctx.settings.contexts:
            msg = f"Document context not found: '{context_id}'"
            if context_id != sanitized_id:
                msg = f"{msg} (sanitized: '{sanitized_id}')"
            raise click.ClickException(msg)

        context: datorum.DocumentContext = app_ctx.settings.contexts[sanitized_id]

        context_base = context.base_path.resolve()
        doc_path = doc_file.resolve()

        try:
            relative_path = doc_path.relative_to(context_base)
        except ValueError:
            raise click.ClickException(
                f"Document is not in the context path "
                f"(document in '{doc_file}', context in '{context.base_path}')")

        parts = relative_path.parts
        document_id = ".".join(parts)

        context.create_document(
            id=document_id,
            doc_type=doc_type,
            doc_model=doc_model,
        )
        app_ctx.settings.save()

        click.echo("Done!")


    @staticmethod
    @cli_command("export")
    @click.argument("context_id")
    @click.argument("output_file", type=click.Path(path_type=Path))
    @click.pass_obj
    def export_context(
        app_ctx: CliAppContext,
        context_id: str,
        output_file: Path,
    ):
        click.echo(f"Exporting document context '{context_id}' to '{output_file}'...")

        sanitized_id = _sanitize_id(context_id)
        if sanitized_id not in app_ctx.settings.contexts:
            msg = f"Document context not found: '{context_id}'"
            if context_id != sanitized_id:
                msg = f"{msg} (sanitized: '{sanitized_id}')"
            raise click.ClickException(msg)

        context: datorum.DocumentContext = app_ctx.settings.contexts[sanitized_id]
        context.save_as(output_file)

        click.echo("Done!")


class ConfigGroup(BaseCommandGroup):
    """Group for configuration commands."""

    def __init__(self, name=None, **attrs):
        super().__init__(name=name, **attrs)
        self.add_command(ContextGroup(
            name="context",
            help="Manages document context settings."
        ))

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

