# Datorum

An AI agent specialized in context engineering.


## Goal

The main goal of this project is to provide a consistent set of context engineering tools, aimed at preparing smaller LLMs for highly specialized tasks, thereby reducing the cost and environmental impact of everyday AI tool usage.


## Current state

The project currently has a scraping mechanism with some specializations for sources (e.g. `archive.org` and `arxiv`) and formats (e.g. `MDX` and `QMD`), and a small agent for segmenting acquired content into semantic chunks. The available tools can be accessed through a terminal client.


## Next steps

- Vector database and semantic search.
- Scraping agent that customizes Scrapers by tooling, according to each specific case.
- Running agents as a daemon, with monitoring and interaction ("HITL" - human in the loop) via CLI and via context file (markdown frontmatter).
- Tool for preparing context for interaction with an LLM (chatbot, agent, etc).


## How to use

### Installing

After cloning the project, simply install via PIP:

```
pip install -e .
```

### Setting up the environment

Configuration can be handled via environment variables or a `.env` file. The main configuration settings are:

- `DATA_DIR`: Working directory where generated data will be stored.
- `CHUNKER_BASE_URL`: URL for accessing the chunker inference server.
- `CHUNKER_API_KEY`: Access key for the chunker inference server.
- `CHUNKER_MODEL`: Name of the model that will perform the chunking.

### Configuring sources

Information sources are organized into domains, in the `{DATA_DIR}/domains.json` file, which follows this format:

```json
{
    "id": "domain-id",
    "slug": "domain-slug",
    "name": "Domain Name",
    "topics": [
        {
            "id": "topic-id",
            "slug": "topic-slug",
            "name": "Topic Name",
            "sources": [
                {
                    "id": "source-id",
                    "slug": "source-slug",
                    "name": "Source Name",
                    "url": "https://source.url",
                    "source_file": "scraped_info.md",
                    "chunks_file": "semantic_chunked.json",
                    "scraper": "ScraperClass",
                    "scraper_args": {
                        "key": "val"
                    }
                }, { ... }
            ]
        }, { ... }
    ]
}
```

### Downloading information (`scrape`)

```
datorum scrape source-id
```

### Generating semantic chunks (`chunk`)

```
datorum chunk source-id
```

## License

This software may be used, including commercially, under the terms of the [Apache 2.0](LICENSE) license.