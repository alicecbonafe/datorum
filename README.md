# Datorum

A settings-based framework for creating AI agents and pipelines, focusing on the high specialization of smaller models using context engineering.

## Goal

The main goal of this project is to provide a consistent set of context engineering tools, aimed at preparing smaller LLMs for highly specialized tasks, thereby reducing the cost and environmental impact of everyday AI tool usage.

## Quick start

**TODO** About simple install

```
python -m venv datorum
source ./datorum/bin/activate
pip install git+https://codeberg.org/alicebonafe/datorum.git
datorum init-config
```

**TODO** About edit settings

**TODO** About run jobs


## About the name

> "Contextus est subiectum; Datorum est obiectum."
> (Context is the subject; Datorum is the object.)

Datorum derives from the Latin genitive plural datōrum, meaning "of the data".

In Latin syntax, the Subject takes the nominative case, while the direct Object takes the accusative. There's a deliberate philosophical stance in naming this framework Datorum (genitive): the Context is the active subject that drives the LLM interaction, but Datorum is the framework that exists in relation to the data. It is not the protagonist; it is the grammatical object that belongs intrinsically to the information it processes. Datorum bends to the data, serving as the oblique tool through which the subject (context) transforms raw information into intelligence.

It's pronounced /da.ˈtoː.rũː/ in Classical Latin — in practice, say da-TOH-rum (rhymes with 'serum' in English, or simply 'Datôrum' as in Brazilian Portuguese).For Mandarin speakers, a natural rendering is 达-托-鲁姆 (Dā-tuō-lǔ-mǔ), with a slight pitch emphasis on the second syllable "tuō" to preserve the Latin stress.

## Current state

The entire architecture has been redesigned to provide a solid foundation for work. Contexts and resources can be shared via global or local registries, allowing for complete flexibility. Toolkits can be executed by the user, by AI agents, or as pipeline steps.


## Next steps

### Still for this version

- Basic CLI application for start and monitor jobs.
- Integration between `datorum.work.job.Job.log_broadcaster` property with the built-in `logging` package.
- Full docstrings for all elements exposed by `src/datorum/__init__.py`, in reST format.
- Quality report build in dev time (published via repo, not PyPi).
- Quality report build in CI time (artifact).

### For future versions

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

**TODO**

### Configuring sources

**TODO**

## License

This software may be used, including commercially, under the terms of the [Apache 2.0](LICENSE) license.