import argparse
import logging
from pathlib import Path

from pydantic import BaseModel, Field, PrivateAttr
import typer

from . import configure_logging, get_logger
from .model.config import GeneralConfig
from .model.domains import DomainCollection, Domain, Source


APP_NAME = "datorum"

DEFAULT_PATH = Path(typer.get_app_dir(APP_NAME))


app = typer.Typer()


config_app = typer.Typer(help="Configuration commands")

config_provider_app = typer.Typer(help="Provider configuration commands")
config_provider_model_app = typer.Typer(help="Provider model configuration commands")
config_provider_app.add_typer(config_provider_model_app, name="provider")
config_app.add_typer(config_provider_app, name="provider")

config_role_app = typer.Typer(help="Role configuration commands")
config_app.add_typer(config_role_app, name="role")

config_agent_app = typer.Typer(help="Agent configuration commands")
config_agent_alias_app = typer.Typer(help="Agent alias configuration commands")
config_agent_app.add_typer(config_agent_alias_app, name="alias")
config_app.add_typer(config_agent_app, name="agent")

app.add_typer(config_app, name="config")


domain_app = typer.Typer(help="Domain related commands")

source_app = typer.Typer(help="Source related commands")
domain_app.add_typer(source_app, name="source")

app.add_typer(domain_app, name="domain")


scraper_app = typer.Typer(help="Scraper commands")
app.add_typer(scraper_app, name="scraper")


chunker_app = typer.Typer(help="Chunker commands")
app.add_typer(chunker_app, name="chunker")


class GlobalState(BaseModel):

    verbose: int
    config_dir: Path
    non_iteractive: bool

    _config: GeneralConfig | None = PrivateAttr(default=None)
    _domain_collection: DomainCollection | None = PrivateAttr(default=None)

    @property
    def config(self) -> GeneralConfig:
        if self._config is None:
            if self.config_dir is None:
                raise ValueError("Application is not configured yet")
            if not self.config_dir.exists():
                raise ValueError("Configuration was not initialized, please run 'datorum config init <data_path>'")
            self._config = GeneralConfig.load(self.config_dir / "config.yml")
        return self._config

    @property
    def domain_collection(self) -> DomainCollection:
        if self._domain_collection is None:
            self._domain_collection = DomainCollection.load(
                self.config.data_dir / "domains.yml")
        return self._domain_collection

@app.callback()
def main(
    ctx: typer.Context,
    verbose: int = typer.Option(
        False, "--verbose", "-v",
        count=True, help="Enable verbose logging"),
    config_dir: Path = typer.Option(
        DEFAULT_PATH, "--config-dir",
        help="Directory containing config and API keys"),
    non_iteractive: bool = typer.Option(
        False, "--non-interactive",)
):
    """Datorum: tool box and agent manager for context engineering."""
    gstate = GlobalState(
        verbose=verbose,
        config_dir=config_dir,
        non_iteractive=non_iteractive,
    )
    ctx.obj = gstate

    log_level: int = logging.WARNING
    if verbose == 1:
        log_level = logging.INFO
    elif verbose > 1:
        log_level = logging.DEBUG
    configure_logging(log_level)

# CONFIG COMMANDS #############################################################

@config_app.command("init")
def config_init(
    ctx: typer.Context,
    data_dir: Path,
    *,
    log_file: Path | None = None,
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite if config file already exists."),
):
    """Create the initial config file."""
    gstate: GlobalState = ctx.obj

    if gstate._config is not None and not force:
        print("Config file already exists, use '--force' to overwrite.")
        exit(1)

    gstate.config_dir.mkdir(parents=True, exist_ok=True)
    data_full_path: Path = data_dir.absolute()
    gstate._config = GeneralConfig(
        data_dir = data_full_path,
        log_file = log_file,
    )
    config_file = gstate.config_dir / 'config.yml'
    gstate._config.save(config_file)
    print(f"Default config file stored at {str(config_file)}")

@config_app.command("get")
def config_get(
    ctx: typer.Context,
    prop: str | None = typer.Argument(
        None, help="Name of the property to retraive, omit will dump all basic properties."
    ),
): ...

@config_app.command("set")
def config_set(
    ctx: typer.Context,
    data_dir: Path | None = typer.Option(
        None, "--data-dir",
        help="Path for the data directory."),
    log_file: Path | None = typer.Option(
        None, "--log-file",
        help="Path for the log file."),
): ...

@config_app.command("connect-os-keychain")
def config_connect_os_keychain(
    ctx: typer.Context,
    service: str = typer.Argument(help="Keychain namespace."),
    migrate: bool = typer.Option(
        False, "--migrate", "-m",
        help="Migrate store keys, if any."),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="If migrate is off, set force to true for overwriting the configuration (will raise exception otherwise)."),
): ...

@config_app.command("create-encrypted-file")
def config_create_encrypted_file(
    ctx: typer.Context,
    file_path: Path = typer.Argument(help="Path to the encrypted file."),
    iterations: int | None = typer.Argument(
        None, help="Key derivation iterations."),
    migrate: bool = typer.Option(
        False, "--migrate", "-m",
        help="Migrate store keys, if any."),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="If 'migrate' is off, set 'force' to true for overwriting the configuration (will raise exception otherwise)."),
): ...

@config_provider_app.command("list")
def config_provider_list(
    ctx: typer.Context,
): ...

@config_provider_app.command("get")
def config_provider_get(
    ctx: typer.Context,
    id: str = typer.Argument(help="Provider ID."),
    prop: str | None = typer.Argument(
        None, help="Name of the property to retraive, omit will dump all basic properties."
    ),
): ...

@config_provider_app.command("set")
def config_provider_set(
    ctx: typer.Context,
    id: str = typer.Argument(help="Provider ID."),
    base_url: str | None = typer.Option(
        None, "--base-url",
        help="API endpoint base URL (required if the provider is not created yet)"),
    description: str | None = typer.Option(
        None, "--description",
        help="A helpful description for this provider."),
    default_model: str | None = typer.Option(
        None, "--default-model",
        help="Fallback when no model is selected."),
): ...

@config_provider_app.command("del")
def config_provider_del(
    ctx: typer.Context,
    id: str = typer.Argument(help="Provider ID."),
    prop: str | None = typer.Argument(
        None, help="Name of the property to retraive, omit will dump all properties."
    ),
): ...

@config_provider_app.command("set-key")
def config_provider_set_key(
    ctx: typer.Context,
    id: str = typer.Argument(help="Provider ID."),
): ...

@config_provider_model_app.command("list")
def config_provider_model_list(
    ctx: typer.Context,
    id: str = typer.Argument(help="Provider ID."),
): ...

@config_provider_model_app.command("add")
def config_provider_model_add(
    ctx: typer.Context,
    id: str = typer.Argument(help="Provider ID."),
    models: list[str] = typer.Argument(help="Models to add"),
): ...

@config_provider_model_app.command("drop")
def config_provider_model_drop(
    ctx: typer.Context,
    id: str = typer.Argument(help="Provider ID."),
    models: list[str] = typer.Argument(help="Models to drop"),
): ...

@config_role_app.command("list")
def config_role_list(
    ctx: typer.Context,
): ...

@config_role_app.command("get")
def config_role_get(
    ctx: typer.Context,
    id: str = typer.Argument(help="Role ID."),
    prop: str | None = typer.Argument(
        None, help="Name of the property to retraive, omit will dump all properties."
    ),
): ...

@config_role_app.command("set")
def config_role_set(
    ctx: typer.Context,
    id: str = typer.Argument(help="Role ID."),
    type: str | None = typer.Option(
        None, "--type",
        help="Type for this role (only used for new roles)."),
    description: str | None = typer.Option(
        None, "--description",
        help="A helpful description for this role."),
    temperature: float | None = typer.Option(
        None, "--temperature",
        help="Temperature (only for inference roles)."),
    top_p: float | None = typer.Option(
        None, "--top-p",
        help="Top P (only for inference roles)."),
    max_tokens: int | None = typer.Option(
        None, "--max-tokens",
        help="Max generated tokens (only for inference roles)."),
    dimensions: int | None = typer.Option(
        None, "--dimensions",
        help="Requested vector size, if the model supports truncation (only for embedding roles)."),
    batch_size: int | None = typer.Option(
        None, "--batch-size",
        help="Chunks per embedding request (only for embedding roles)."),
): ...

@config_role_app.command("set-instructions-template")
def config_role_set_instructions_template(
    ctx: typer.Context,
    id: str = typer.Argument(help="Role ID."),
): ...

@config_role_app.command("del")
def config_role_del(
    ctx: typer.Context,
    id: str = typer.Argument(help="Role ID."),
): ...

@config_agent_app.command("list")
def config_agent_list(
    ctx: typer.Context,
): ...

@config_agent_app.command("get")
def config_agent_get(
    ctx: typer.Context,
    id: str = typer.Argument(help="Agent ID."),
    prop: str | None = typer.Argument(
        None, help="Name of the property to retraive, omit will dump all properties."
    ),
): ...

@config_agent_app.command("set")
def config_agent_set(
    ctx: typer.Context,
    id: str = typer.Argument(help="Agent ID."),
    provider: str | None = typer.Option(
        None, "--provider",
        help="Provider ID for this agent."),
    role: str | None = typer.Option(
        None, "--role",
        help="Role ID for this agent."),
): ...

@config_agent_app.command("del")
def config_agent_del(
    ctx: typer.Context,
    id: str = typer.Argument(help="Agent ID."),
    prop: str | None = typer.Argument(
        None, help="Name of the property to retraive, omit will dump all basic properties."
    ),
): ...

@config_agent_alias_app.command("list")
def config_agent_alias_list(
    ctx: typer.Context,
    id: str = typer.Argument(help="Agent ID."),
): ...

@config_agent_alias_app.command("add")
def config_agent_alias_add(
    ctx: typer.Context,
    id: str = typer.Argument(help="Agent ID."),
    aliases: list[str] = typer.Argument(help="Aliases to add"),
): ...

@config_agent_alias_app.command("drop")
def config_agent_alias_drop(
    ctx: typer.Context,
    id: str = typer.Argument(help="Agent ID."),
    aliases: list[str] = typer.Argument(help="Aliases to drop"),
): ...

# DOMAIN COMMANDS #############################################################

def _get_domain_or_exit(collection: DomainCollection, domain_id: str) -> Domain:
    """Resolve domain_id to a Domain node, or exit with an error."""
    node = collection.get(domain_id)
    if node is None:
        typer.echo(f"Domain '{domain_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if not isinstance(node, Domain):
        typer.echo(f"'{domain_id}' is a source, not a domain.", err=True)
        raise typer.Exit(code=1)
    return node

@domain_app.command("list")
def domain_list(
    ctx: typer.Context,
    domain_id: str | None = None,
    recursive: bool = typer.Option(
        False, "--recursive", "-r",
        help="Recursively list subdomains."),
):
    """List the children of a domain."""
    gstate: GlobalState = ctx.obj
    collection = gstate.domain_collection
    domain = _get_domain_or_exit(collection, domain_id) if domain_id else collection

    if recursive:
        for node in domain.walk():
            kind = "domain" if isinstance(node, Domain) else "source"
            typer.echo(f"[{kind}] {node.full_id}")
    else:
        for child in domain.domains:
            typer.echo(f"[domain] {child.full_id}")
        for source in domain.sources:
            typer.echo(f"[source] {source.full_id}")

@domain_app.command("get")
def domain_get(
    ctx: typer.Context,
    domain_id: str,
    description: bool = False,
    metadata: bool = False):
    """Show a domain's basic info."""
    gstate: GlobalState = ctx.obj
    collection = gstate.domain_collection
    domain = _get_domain_or_exit(collection, domain_id)

    typer.echo(f"id: {domain.full_id or '(root)'}")
    typer.echo(f"name: {domain.name or '-'}")
    if description:
        typer.echo(f"description: {domain.description or '-'}")
    if metadata:
        typer.echo(f"metadata:")
        for _k, _v in domain.metadata.items():
            typer.echo(f"  {_k}: {_v}")

@domain_app.command("set")
def domain_set(ctx: typer.Context, domain_id: str, name: str, description: str | None = None):
    """Create or update a domain's name/description (creates missing parents too)."""
    gstate: GlobalState = ctx.obj
    collection = gstate.domain_collection

    domain = collection.create_domain(domain_id)
    domain.name = name
    if description is not None:
        domain.description = description

    collection.save()
    typer.echo(f"Domain '{domain.full_id}' saved.")

@domain_app.command("get-metadata")
def domain_get_metadata(ctx: typer.Context, domain_id: str, key: str):
    """Print a single metadata value for a domain."""
    gstate: GlobalState = ctx.obj
    collection = gstate.domain_collection
    domain = _get_domain_or_exit(collection, domain_id)

    if key not in domain.metadata:
        typer.echo(f"Key '{key}' not found on domain '{domain.full_id}'.", err=True)
        raise typer.Exit(code=1)

    typer.echo(domain.metadata[key])

@domain_app.command("set-metadata")
def domain_set_metadata(ctx: typer.Context, domain_id: str, key: str, value: str | None = None):
    """Set a metadata key/value pair on a domain."""
    gstate: GlobalState = ctx.obj
    collection = gstate.domain_collection
    domain = _get_domain_or_exit(collection, domain_id)

    if value is None:
        del domain.metadata[key]
    else:
        domain.metadata[key] = value
    collection.save()
    typer.echo(f"Metadata '{key}' set on domain '{domain.full_id}'.")

@domain_app.command("del")
def domain_delete(ctx: typer.Context, domain_id: str, force: bool = False):
    """Delete a domain (and optionally its children)."""
    gstate: GlobalState = ctx.obj
    collection = gstate.domain_collection
    domain = _get_domain_or_exit(collection, domain_id)

    if domain is collection:
        typer.echo("Cannot delete the root domain.", err=True)
        raise typer.Exit(code=1)

    if (domain.domains or domain.sources) and not force:
        typer.echo(
            f"Domain '{domain.full_id}' is not empty, use '--force' to delete it "
            "and all its children.",
            err=True,
        )
        raise typer.Exit(code=1)

    parent = domain.parent
    assert parent is not None  # guaranteed since domain is not the root collection
    parent.domains.remove(domain)
    collection.save()
    typer.echo(f"Domain '{domain.full_id}' deleted.")

# SOURCE COMMANDS #############################################################

@source_app.command("get")
def source_get(
    ctx: typer.Context,
    source_id: str,
    prop: str | None = None,
): ...

@source_app.command("set")
def source_set(
    ctx: typer.Context,
    source_id: str,
    name: str | None = None,
    description: str | None = None,
    url: str | None = None,
    source_file: str | None = None,
    chunks_file: str | None = None,
    scraper: str | None = None,
): ...

@source_app.command("get-metadata")
def source_get_metadata(
    ctx: typer.Context,
    source_id: str,
    key: str,
): ...

@source_app.command("set-metadata")
def source_set_metadata(
    ctx: typer.Context,
    source_id: str,
    key: str,
    value: str | None = None,
): ...

# SCRAPE COMMANDS #############################################################

@scraper_app.command("get")
def scraper_get_arg(
    ctx: typer.Context,
    source_id: str,
    key: str,
): ...

@scraper_app.command("set")
def scraper_set_arg(
    ctx: typer.Context,
    source_id: str,
    key: str,
    value: str | None = None,
): ...

@scraper_app.command("run")
def scraper_run(
    ctx: typer.Context,
    source_id: str,
): ...

# CHUNK COMMANDS ##############################################################




if __name__ == "__main__":
    app()  # pragma: no cover
