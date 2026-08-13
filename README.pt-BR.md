# Datorum

Um framework para criação de agentes de IA baseada em configurações, com foco alta especialização de modelos menores usando engenharia de contexto.


## Objetivo

O principal objetivo deste projeto é fornecer um conjunto consistente de ferramentas de engenharia de contexto, visando a preparação de LLM's menores para tarefas altamente especializadas, diminuindo assim o custo e o impacto ambiental do uso cotidiano de ferramentas de IA.


## Estado atual

O projeto atualmente conta com um mecanismo de scraping com algumas especializações para fontes (p.ex. `archive.org` e `arxiv`) e formatos (p.ex. `MDX` e `QMD`), e um pequeno agente para segmentação do conteúdo adquirido em chunks semânticos. As ferramentas disponíveis podem ser acessadas por um cliente para terminal.


## Próximos passos

- Banco de dados vetorial e busca semântica.
- Agente para scraping, que customiza os Scrapers por tooling, de acordo com cada caso concreto.
- Execução dos agentes como daemon, com monitoramento e interação ("HITL" - humano no loop) por Cli e por arquivo de contexto (markdown frontmatter).
- Ferramenta para preparação de contexto para interação com LLM (chatbot, agente, etc).


## Como usar

### Instalando

Depois de clonar o projeto, basta instalar via PIP:

```
pip install -e .
```

### Configurando o ambiente

Nesse momento, as configurações podem ser feitas por variáveis de ambiente ou por um arquivo `.env`. Essas são as principais configurações existentes:

- `DATA_DIR`: Diretório de trabalho, onde serão armazenados os dados gerados.
- `CHUNKER_BASE_URL`: URL para acesso ao servidor de inferência para o chunker.
- `CHUNKER_API_KEY`: Chave de acesso do servidor de inferência para o chunker.
- `CHUNKER_MODEL`: Nome do modelo que performará o chunk.

### Configurando fontes

As fontes de informações são organizadas em domínios, no arquivo `{DATA_DIR}/domains.json`, que segue o seguinte formato:

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

### Baixando informações (`scrape`)

```
datorum scrape source-id
```

### Gerando chunks semânticos (`chunk`)

```
datorum chunk source-id
```

## Licença

Este software pode ser usado, inclusive comercialmente, sob os termos da licença [Apache 2.0](LICENSE).

