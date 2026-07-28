import argparse
from pathlib import Path

from pydantic import BaseModel, Field, PrivateAttr

from .model.config import GeneralConfig
from .model.domains import DomainCollection, Domain, Source
from .exceptions import ChunkerException, ScraperException
from .providers.inference import InferenceProvider, InferenceRequest
from .scrapers import registry


class Chunk(BaseModel):
    id: str = Field(description="Composed id for this chunk")
    content: str = Field(description="Chunk text content")
    section_path: str = Field(description="Section path")
    chunk_type: str = Field(description="A meaningful classifier")
    related: list[str] = Field(
        description="IDs of related chunks", default_factory=list
    )
    metadata: list[str] = Field(
        description="Relevant classifiers", default_factory=list
    )


class ChunkedDocument(BaseModel):
    title: str = Field(description="Document title")
    tags: list[str] = Field(description="Meaningful tags", default_factory=list)
    chunks: list[Chunk] = Field(
        description="List of semantic splited chunks", default_factory=list
    )


def _app():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", help="Path to the data directory.")
    parser.add_argument("command", help="Command name", choices=["scrape", "chunk"])
    parser.add_argument("source_id", help="ID of the source to scrape")
    args = parser.parse_args()
    datapath_str: str | None = args.data_path
    command: str = args.command
    source_id: str = args.source_id

    datapath: Path
    if datapath_str is None:
        datapath = Path(GeneralConfig["DATA_DIR"])
    else:
        GeneralConfig["DATA_DIR"] = datapath_str
        datapath = Path(datapath_str)

    domain_collection = DomainCollection.load(datapath / 'domains.yml')
    source: Source = domain_collection[source_id]

    match command:
        case "scrape":
            if source.scraper is None:
                raise ScraperException("Source doesn't define a scraper")
            if source.url is None:
                raise ScraperException("Source doesn't define an URL")

            scraper = registry[source.scraper]()  # type: ignore[abstract]
            source.source_path.parent.mkdir(parents=True, exist_ok=True)
            scraper.scrape_from(source.url, source.source_path, **source.scraper_args)
        case "chunk":
            system_file = domain_collection.data_dir / "instructions.md"

            with system_file.open("r", encoding="utf-8") as f:
                system_instructions = f.read()
            with source.source_path.open("r", encoding="utf-8") as f:
                user_prompt = f.read()

            chunker_model = (
                GeneralConfig["CHUNKER_MODEL"]
                if "CHUNKER_MODEL" in GeneralConfig
                else GeneralConfig["MODEL"]
            )
            if not chunker_model:
                raise ChunkerException("Model not defined")

            request = InferenceRequest(
                model=chunker_model,
                system_instructions=system_instructions,
                user_prompt=user_prompt,
                temperature=0.7,
                max_tokens=65536,
                response_schema=ChunkedDocument,
            )

            print(f"Generating chunks for {source.full_id}...")

            response = InferenceProvider.load("chunker").generate(request)

            chunks_path = source.chunks_path
            chunks_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"Saving as {chunks_path!s}...")
            with chunks_path.open("w", encoding="utf-8") as f:
                f.write(response or "")
            print("Done!")


import logging
import typer


from . import configure_logging, get_logger


APP_NAME = "datorum"

DEFAULT_PATH = Path(typer.get_app_dir(APP_NAME))

app = typer.Typer()

config_app = typer.Typer(help="Configuration commands")
app.add_typer(config_app, name="config")

domain_app = typer.Typer(help="Domain related commands")
app.add_typer(domain_app, name="domain")

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
        False, "--non-interactive",
        help="Stop asking permission")
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

@config_app.command("init")
def config_init(
    ctx: typer.Context,
    data_dir: Path,
    force: bool = False
):
    """Create the initial config file."""
    gstate: GlobalState = ctx.obj

    if gstate._config is not None and not force:
        print("Config file already exists, use '--force' to overwrite.")
        exit(1)

    gstate.config_dir.mkdir(parents=True, exist_ok=True)
    data_full_path: Path = data_dir.absolute()
    gstate._config = GeneralConfig(data_dir = data_full_path)
    gstate._config.save(gstate.config_dir / 'config.yml')


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
def domain_set_metadata(ctx: typer.Context, domain_id: str, key: str, value: str):
    """Set a metadata key/value pair on a domain."""
    gstate: GlobalState = ctx.obj
    collection = gstate.domain_collection
    domain = _get_domain_or_exit(collection, domain_id)

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


source_app = typer.Typer(help="Source related commands")
app.add_typer(source_app)

scraper_app = typer.Typer(help="Scraper commands")
app.add_typer(scraper_app)

chunker_app = typer.Typer(help="Chunker commands")
app.add_typer(chunker_app)


if __name__ == "__main__":
    app()  # pragma: no cover
