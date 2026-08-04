# Datorum — Refactoring Plan v1

## 0. Context & scope

Datorum today is a small, working CLI: `domains.json` describes a tree of
`domain → topic → source`, each source points at a `scraper` (looked up in a
flat `registry` dict) with free-form `scraper_args`, and a single
`InferenceFactory` wraps an OpenAI-compatible client for the LLM chunking
step. Config comes from `.env` merged with `os.environ` into one dict.

This refactor has four goals, in the order they build on each other:

1. **OSS-readiness** — packaging, docs, license, CI, tests.
2. **Config overhaul** — user config files instead of `.env`, with encrypted
   API keys.
3. **Migration from CLI to endpoints** — so it can serve any specialized frontend.
   A small but complete app using NiceGUI will be create as reference GUI
   implementation.
4. **Decoupling for the scraper-routing agent** — give scrapers declared,
   introspectable parameters so a future local-model agent can pick a
   scraper and tune its args per task.

The plan below sequences the work so each phase leaves the tool fully
working — no long-lived broken branches.

---

## 1. Guiding principles

- **Behavior-preserving first, restructure second.** All functionalities
  implemented (`scrap`/`chunk`) needs to be forged as tools and agents.
- **Data model before GUI.** The endpoint construction is only save once
  all data model is complete, including config, domains, and pipelines, as
  well as all functionalities migrated for the tooling architecture.
- **Secrets are a separate concern from config.** The config file should be
  safe to commit to a dotfiles repo or share as an example; it never holds
  raw key material, only references to entries in the secret store.

---

## 2. Phase 0 (complete) — Safety net

**Deliverable:** green test suite that pins current behavior, runnable
locally from here on.

---

## 3. Phase 1 (complete) — Packaging & OSS skeleton

- [x] `pyproject.toml`.
- [x] Console entry point: `datorum = "datorum.cli:app"`.
- [x] `LICENSE` — **Apache-2.0**
- [x] `README.md`.
- [x] CI pipeline
- [x] Rename the `scrap` command to `scrape`.

**Deliverable:** `pip install -e .` gives a working `datorum` command,
lint/tests are easy to run locally, repo is presentable.

---

## 4. Phase 2 (complete) — Domain data model

**Deliverable:** all reads/writes of `domains.yml` go through one class;
`scrap`/`chunk` behave exactly as before.

> Dropped the `Topic` data structure and made `Domain` recursive.
> Changed persisted file to YAML.
> All data can be accessed, stored and loaded using `DomainCollection`.
> All changes integrated and all tests implemented.

---

## 5. Phase 3 (current) — Full settings model

Commom base for all Datorum use cases.

- Configuration for global definitions, including API settings, key storage
  security and agent roles.
- Data classes for pipeline steps (human, tool and agent) with shared toolboxes
  definitions, separated files for execution control.
- Context binding model

- [x] Coding
- [ ] Testing
- [ ] Styling

---

## 6. Phase 4 — Runners for tools, agents and pipelines



---

## 7. Phase 3 — Basic tools

- FileManager
- SiteScraper (must implement a strong `robots.txt` compliance)
- GitBrowser
- HTMLDocParser (selector based)
- MatchDocParser (pattern based)
- DirectDataConverter
- VectorDBManager
- SnippetRunner


---

## 8. Phase 6 — FastAPI endpoints



---

## 9. Phase 7 — Reference GUI implementation (NiceGUI)



---

## 10. Phase 8 — Documentation



---

## 11. Phase 9 — First release


