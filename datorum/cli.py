import argparse
from pathlib import Path

from pydantic import BaseModel, Field

from . import GeneralConfig
from .domains import DomainCollection, Source
from .scrapers import registry
from .providers.inference import InferenceRequest, InferenceProvider

class Chunk(BaseModel):
    id: str = Field(description = "Composed id for this chunk")
    content: str = Field(description = "Chunk text content")
    section_path: str = Field(description = "Section path")
    chunk_type: str = Field(description = "A meaningful classifier")
    related: list[str] = Field(description = "IDs of related chunks", default_factory=list)
    metadata: list[str] = Field(description="Relevant classifiers", default_factory=list)


class ChunkedDocument(BaseModel):
    title: str = Field(description = "Document title")
    tags: list[str] = Field(description = "Meaningful tags", default_factory=list)
    chunks: list[Chunk] = Field(description = "List of semantic splited chunks", default_factory=list)


def app():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", help="Path to the data directory.")
    parser.add_argument("command", help="Command name", choices = ['scrape', 'chunk'])
    parser.add_argument("source_id", help="ID of the source to scrape")
    args = parser.parse_args()
    data_path: str|None = args.data_path
    command: str = args.command
    source_id: str = args.source_id

    if data_path is not None:
        GeneralConfig['DATA_DIR'] = data_path

    domain_collection = DomainCollection.load()
    source: Source = domain_collection[source_id]

    match command:
        case 'scrape':
            scraper = registry[source.scraper]()
            source.source_path.parent.mkdir(parents=True, exist_ok=True)
            scraper.scrape_from(
                source.url,
                source.source_path,
                **source.scraper_args
            )
        case 'chunk':
            system_file = domain_collection.data_dir / 'instructions.md'

            with system_file.open('r', encoding='utf-8') as f:
                system_instructions = f.read()
            with source.source_path.open('r', encoding='utf-8') as f:
                user_prompt = f.read()

            request = InferenceRequest(
                model = GeneralConfig['CHUNKER_MODEL'],
                system_instructions = system_instructions,
                user_prompt = user_prompt,
                temperature = .7,
                max_tokens = 65536,
                response_schema = ChunkedDocument,
            )

            print(f"Generating chunks for {source.full_id}...")

            response = InferenceProvider.load('chunker').generate(request)

            chunks_path = source.chunks_path
            chunks_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"Saving as {str(chunks_path)}...")
            with chunks_path.open('w', encoding = 'utf-8') as f:
                f.write(response)
            print("Done!")



if __name__ == "__main__":
    app() # pragma: no cover