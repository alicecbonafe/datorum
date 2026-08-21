# Datorum

A settings-based framework for creating AI agents and pipelines, focusing on the high specialization of language models using context engineering.

## Goal

Datorum aims to provide a consistent context engineering framework to prepare LLMs for highly specialized tasks. The working premise is that careful context structuring can reduce the required number of input and reasoning tokens, making smaller or quantized models a practical substitute for larger, context-naive models in specific domains.

This is currently as much an investigative effort as an engineering one. The field of context engineering is still formative. Effective combinations of techniques are not well understood, and many assumptions remain unverified. Datorum is therefore also being built as an experimental laboratory, intended to support the combination, iteration, and evaluation of different context strategies.

Once the core features stabilize, it will be possible to run controlled benchmarks to establish the efficiency and quality of different techniques in specific contexts.

## About the name

> "Contextus est subiectum; Datorum est obiectum."
> (Context is the subject; Datorum is the object.)

Datorum derives from the Latin genitive plural datōrum, meaning "of the data".

In Latin syntax, the Subject takes the nominative case, while the direct Object takes the accusative. There's a deliberate philosophical stance in naming this framework Datorum (genitive): the Context is the active subject that drives the LLM interaction, and Datorum is the framework that exists in relation to the data. It is not the protagonist; it is the grammatical object that belongs intrinsically to the information it processes. Datorum bends to the data, serving as the oblique tool through which the subject (context) transforms raw information into intelligence.

It's pronounced /da.ˈtoː.rũː/ in Classical Latin — in practice, say da-TOH-rum (rhymes with 'serum' in English, or simply 'Datôrum' as in Brazilian Portuguese). For Mandarin speakers, a natural rendering is 达-托-鲁-姆 (Dā-tuō-lǔ-mǔ), with a slight pitch emphasis on the second syllable "tuō" to preserve the Latin stress.

## Current state (as of 0.1.0a1)

The core context‑engineering machinery is in place and fully tested.

- **Document handling**
  Within a context, document settings specify a file type (as stored on disk) and a model type (the corresponding Python representation). The most basic example is a plain text (`doc_type = "text/plain"`) file loaded into a string (`doc_model = "str"`). The framework currently maps 3 file types for structured data: YAML (`doc_type = "applictiona/yaml"`), JSON (`"applictiona/json"`), and TOML (`"applictiona/toml"`). These three file formats can be natively mapped as dictionaries (`doc_mode = "dict"`), and the `@datorum.doc_model` decorator allows transforming any `pydantic.BaseModel` model into a representation valid for these formats. This is demonstrated, for instance, by `datorum.ChatHistory` (`doc_model = "chat-history"`), a comprehensive data structure designed for seamless interaction with inference endpoints, which can be stored in any of these three structured data doc types. The framework also provides the `datorum.Markdown` model (`doc_model = "markdown"`) out of the box, separating the handling of Markdown content from the structured data found in the frontmatter of Markdown files (`doc_type = "text/markdown"`), a feature particularly useful for working with indexed and categorized semantic contexts.

- **Execution layers**
  Three worker types are provided, each with a distinct responsibility:
  - *Tools*: built programmatically and configured through context documents; can be invoked directly by the user, by an LLM using tooling, or as a pipeline step. The standard toolset is still to be implemented.
  - *Agents*: defined via separate providers and roles, with pluggable API‑key resolution to interface with existing security backends. Agents can be forced to execute only tool calls for a fixed number of iterations; the resulting chat history can then be bound to a different role, enabling a clean separation between the model that gathers data and the model that performs inference.
  - *Pipelines*: organised as steps of four types (tool, agent, human‑in‑the‑loop, and decision). Every step points to the next one by ID, except decision steps, which run a user‑supplied script (defined in settings) to determine the following step at runtime. The pipeline state is stored on disk whenever a step completes, allowing for recovery between executions.

  Workers run jobs - asynchronous runtime instances that can be monitored, paused, and resumed - relying on broadcasters for chunks (in the case of provider response streaming), logs, and state updates.

- **CLI**
  Basic configuration operations are available, though most files are still expected to be edited manually. The CLI can invoke all three workers. Pipelines can be invoked in interactive mode (pauses execution at HITL steps and waits for user to choose between resuming or stopping the worker) or non‑interactive mode (terminates on HITL, with the possibility of resuming later).

- **Quality assurance**
  The codebase has 100% test coverage, passes linting checks, and is continuously integrated on both CodeBerg and GitHub. The forthcoming release (0.1.0a1) will be the first published on PyPI.

## Roadmap

The project is being developed in incremental, observable milestones:

- **v0.1.0a2** - documentation
  API reference and usage guides will be written in reStructuredText and published to Read the Docs via CI. A context-management tool will be added to handle auto-discovery and organization of context documents.

- **v0.1.0b1** - core toolset
  In addition to resolving issues encountered in the initial use cases, the version will enter the beta stage once a basic set of tools is implemented out-of-the-box. At that point, the framework must be capable of gathering documents from different sources, normalizing them, and preparing them for search via selector, pattern, or semantics. Also, this basic set of tools must enable context and chat history customizing.

- **v0.1.0** - the workbench
  Starting with the beta version, the focus shifts to developing a web interface capable of handling various file types - such as forms, chat histories, and a syntax - highlighting editor as a fallback for non-binary files. It must also allow users to start, pause, and resume all workers, customize pipeline executions, and monitor all broadcasters. When the workbench is ready for general use, the framework will exit the beta stage, entering version **v0.1.0**, and begin moving toward a stable, production-ready version - namely, **v1.0.0**.

In the long term, the project remains an open laboratory for context engineering, allowing the comparison of different context engineering techniques in different language models, including benchmarks that enable comparison with larger and context-naive models.

## How to use

### Installing

Ensure you have Python 3.14 or later installed. If you want an isolated install, use Python's venv module.

```bash
python -m venv venv-datorum
source ./venv-datorum/bin/activate
```

For a quick installation via pip, you can point directly to the repository.

```bash
pip install git+https://github.com/alicecbonafe/datorum.git
```

For a complete dev install, clone the repository and install the package in development mode.

```bash
git clone https://github.com/alicecbonafe/datorum.git
cd datorum
pip install -e .
```

This will install all the dependencies and link the executable.

### Setting up

Before using Datorum, initialize the configuration file and directory structure.

```bash
datorum config init
```

This creates a .datorum.yml configuration file in the current directory with default settings. The following options are available:

- `-c`, `--contexts`: Specify the path for document contexts (default: `contexts`)
- `-f`, `--flows`: Specify the path for pipeline flows (default: `flows`)
- `-t`, `--flow-id-template`: Set the template for flow IDs (default: `flow_{index}`)
- `-d`, `--sample-data`: Include sample configurations for toolkits, agents, and pipelines

To create a document context for managing files:

```bash
datorum config context create my_context
```

Link existing files to a context:

```bash
datorum config context link my_context data/my_context/path/to/document.yaml --doc-type application/yaml --doc-model dict
```

The command merely creates the reference in the settings; the file does not actually need to exist, as it can be created by tools.

The folder structure is converted into a domain structure separated by `"."`. In this case, `my_context/path/to/document.yaml` will generate a `document_id` of `"path.to.document.yaml"`. To omit the extension, change the document settings by defining the `extension` field. In the following example, the two documents refer to the same file.

```yaml
contexts_path: data
flows_path: flows
flow_id_template: flow_{index}
toolkit:
  toolboxes: ...
agencykit:
  providers: ...
  roles: ...
plumbingkit:
  pipelines: ...
contexts:
  my_context:
    id: my_context
    documents:
      path.to.document.yaml:
        id: path.to.document.yaml
        doc_type: application/yaml
        doc_model: dict
        extension: null
        metadata: {}
      path.to.document:
        id: path.to.document
        doc_type: application/yaml
        doc_model: dict
        extension: yaml
        metadata: {}
    domain_metadata: {}
api_keys: null

```

### Invoking workers

Datorum provides three worker types, each invoked through the datorum run command group.

#### Running tools

Execute a registered tool with input and output documents:

```bash
datorum run tool TOOL_SELECTOR [CONTEXT:]INPUT_DOC [CONTEXT:]OUTPUT_DOC
```

Example:

```bash
datorum run tool my_toolbox.my_tool my_context:path.to.document.yaml my_context:path.to.other.document.yaml
```

Additional context or resource bindings can be specified with -c and -r options respectively.

#### Running agents

Start an agent interaction with a chat history:

```bash
datorum run agent ROLE_ID [CONTEXT:]CHAT_HISTORY_DOC
```

Example:

```bash
datorum run agent my_role my_context:chat_history.json
```

To specify a particular inference provider (otherwise determined from the role's preferred models):

```bash
datorum run agent my_role my_context:chat_history.json --provider my_provider
```

#### Running pipelines

Start a new pipeline flow:

```bash
datorum run pipeline --pipeline PIPELINE_ID
```

Resume an existing flow:

```bash
datorum run pipeline FLOW_ID
```

For non-interactive execution (will terminate at human-in-the-loop steps):

```bash
datorum run pipeline FLOW_ID --non-interactive
```

To create a flow file without executing it:

```bash
datorum run pipeline --pipeline PIPELINE_ID --create-only
```

Pipelines support four step types: tool, agent, human-in-the-loop, and decision. The pipeline state is automatically saved after each step, allowing for recovery between executions.

### Configuration management

Export and import configuration kits for reuse across projects:

```bash
# Export toolkit configuration
datorum config export toolkit tools_config.yml

# Import agency configuration
datorum config import agents agency_config.yml
```

Supported kit types: `toolkit` (or `tools`, `t`), `agencykit` (or `agents`, `a`), `plumbingkit` (or `pipelines`, `pipes`, `p`).

### API keys setup

For quick use of the framework, you can define API keys using environment variables.

```bash
export PROVIDER_ID_API_KEY=your_api_key_value
```

It is also possible to define them directly in the settings file, in plain text. However, for use in a production environment—and to keep your keys secure in general—you can programmatically configure a security backend.

## License

This software may be used, including commercially, under the terms of the [Apache 2.0](LICENSE) license.