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
3. **CLI expansion** — manage domains/topics/sources/providers from the
   terminal, not by hand-editing JSON.
4. **Decoupling for the scraper-routing agent** — give scrapers declared,
   introspectable parameters so a future local-model agent can pick a
   scraper and tune its args per task.

The plan below sequences the work so each phase leaves the tool fully
working — no long-lived broken branches.

---

## 1. Guiding principles

- **Behavior-preserving first, restructure second.** Nothing changes what
  `scrap`/`chunk` actually do until there's a safety net of characterization
  tests to catch regressions.
- **Data model before CLI.** The CLI additions in phase 4 (add/edit
  domain/topic/source/provider) are only safe once `domains.json` is
  accessed through one validated repository class instead of ad-hoc dict
  traversal in `__main__.py`.
- **Schema before agent.** The router agent (phase 5) needs scrapers to
  declare their own parameters. That declaration is useful on its own
  (validation, CLI help, docs) even before any agent exists, so it's built
  as a general improvement, not agent-specific code.
- **Secrets are a separate concern from config.** The config file should be
  safe to commit to a dotfiles repo or share as an example; it never holds
  raw key material, only references to entries in the secret store.

---

## 2. Phase 0 (done) — Safety net

**Deliverable:** green test suite that pins current behavior, runnable
locally from here on (a local `pre-commit`/`make check`, added in phase 1;
hosted CI arrives in phase 9 alongside publishing).

---

## 3. Phase 1 (done) — Packaging & OSS skeleton

- [x] `pyproject.toml`.
- [x] Console entry point: `datorum = "datorum.cli:app"`.
- [x] `LICENSE` — **Apache-2.0**
- [x] `README.md`.
- [x] CI pipeline
- [x] Rename the `scrap` command to `scrape`.

**Deliverable:** `pip install -e .` gives a working `datorum` command,
lint/tests are easy to run locally, repo is presentable.

---

## 4. Phase 2 (done) — Domain data model

**Deliverable:** all reads/writes of `domains.yml` go through one class;
`scrap`/`chunk` behave exactly as before.

> Dropped the `Topic` data structure and made `Domain` recursive.
> Changed persisted file to YAML.
> All data can be accessed, stored and loaded using `DomainCollection`.
> All changes integrated and all tests implemented.

---

## 5. Phase 3 (current) — Configuration, pipeline data model and tooling basic engine

Commom base for all Datorum use cases.

- Configuration for global definitions, including API settings, key storage
  security and agent roles.
- Data classes for pipeline steps (human, tool and agent) with shared toolboxes
  definitions, separated files for execution control.
- Basic tooling engine, with basic toolbox abstract class and tool method decorator.

- [x] Coding
- [ ] Testing
- [ ] Styling

---

## 6. Phase 4 — Basic tools



---

## 7. Phase 5 — Agent runner



---

## 8. Phase 6 — FastAPI endpoints



---

## 9. Phase 7 — Reference GUI implementation (NiceGUI)



---

## 10. Phase 8 — Documentation



---

## 11. Phase 9 — First release


