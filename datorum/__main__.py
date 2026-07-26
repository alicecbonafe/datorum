import argparse
import json
from pathlib import Path

from pydantic import BaseModel, Field

from . import GeneralConfig
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", help="Command name", choices = ['scrap', 'chunk'])
    parser.add_argument("source_id", help="ID of the source to scrap")
    args = parser.parse_args()
    command: str = args.command
    source_id: str = args.source_id

    domain_id = source_id[:1]
    topic_id = source_id[:4]
    work_dir = Path(GeneralConfig.get('DATA_DIR', 'data'))

    domains_file = work_dir / 'domains.json'
    with domains_file.open('r', encoding='utf-8') as f:
        domains = json.load(f)

    domain_metadata : dict = None
    topic_metadata: dict = None
    source_metadata : dict = None
    for _domain in domains:
        if _domain['id'] == domain_id:
            domain_metadata = _domain
            for _topic in domain_metadata['topics']:
                if _topic['id'] == topic_id:
                    topic_metadata = _topic
                    for _source in _topic['sources']:
                        if _source['id'] == source_id:
                            source_metadata = _source
                            break
                    break
            break

    if domain_metadata is None:
        raise Exception(f'Domain not found: {domain_id}')
    if topic_metadata is None:
        raise Exception(f'Topic not found: {topic_id}')
    if source_metadata is None:
        raise Exception(f'Source not found: {source_id}')

    match command:
        case 'scrap':
            scraper = registry[source_metadata['scraper']]()
            scraper.scrap_from(
                source_metadata['url'],
                work_dir / source_metadata['source_file'],
                **source_metadata.get('scraper_args', {})
            )
        case 'chunk':
            system_file = work_dir / 'instructions.md'
            source_file = work_dir / source_metadata['source_file']
            chunks_file = work_dir / source_metadata['chunks_file']

            with source_file.open('r', encoding='utf-8') as f:
                system_instructions = f.read()
            with source_file.open('r', encoding='utf-8') as f:
                user_prompt = f.read()

            request = InferenceRequest(
                model = GeneralConfig['CHUNKER_MODEL'],
                system_instructions = system_instructions,
                user_prompt = user_prompt,
                temperature = .7,
                max_tokens = 65536,
                response_schema = ChunkedDocument,
            )

            print(f"Generating chunks for {source_metadata['slug']}...")

            response = InferenceProvider.load('chunker').generate(request)

            print(f"Saving as {str(chunks_file)}...")
            with chunks_file.open('w', encoding = 'utf-8') as f:
                f.write(response)
            print("Done!")



if __name__ == "__main__":
    main() # pragma: no cover