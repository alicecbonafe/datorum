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

## 2. Phase 0 — Safety net

**Why first:** there are currently no tests. Any restructuring is a gamble
without something to diff behavior against.

- Add `pytest` + a `tests/` tree.
- Characterization tests per scraper using recorded fixtures (`responses` or
  `vcr.py` to mock HTTP) — feed each scraper a canned response and assert
  the `ScrapedDocument` it produces, using the real `data/domains.json`
  entries as the parameter source. This also documents current scraper
  behavior before anything moves.
- One end-to-end test for `datorum scrap <id>` and `datorum chunk <id>`
  against a temp `domains.json` fixture, with `InferenceFactory` mocked out.
- Baseline `ruff` run (lint only, no fixes yet) to catalog existing issues
  without touching code.

**Deliverable:** green test suite that pins current behavior, run in CI
(added in phase 1) from here on.

---

## 3. Phase 1 — Packaging & OSS skeleton

- `pyproject.toml` (hatchling or setuptools — either is fine; hatchling is
  less config for a pure-Python package like this) replacing the implicit
  `requirements.txt`-style setup. Pin real version ranges for `requests`,
  `beautifulsoup4`, `pydantic`, `openai`, `python-dotenv`, `pyyaml`.
- Console entry point: `datorum = "datorum.cli:app"` (the `cli` module
  arrives in phase 4; until then it can point at the existing
  `__main__.main`).
- `LICENSE` — given the project redistributes scraped public-domain/OSS-doc
  content and is itself a tool, Apache-2.0 or MIT both fit; Apache-2.0 adds
  an explicit patent grant, which is worth having if this gets external
  contributors. **Needs your call**, noted in the open questions below.
- `README.md` (what Datorum does, quickstart, one example domain/source),
  `CONTRIBUTING.md`, `CHANGELOG.md`, `.gitignore` hardened to exclude
  `.env`, the new config dir, and any secrets file.
- GitHub Actions CI: lint (`ruff`), format check, `pytest`, on PR + push.
- Rename the `scrap` command to `scrape` (keep `scrap` as a silent alias for
  one release) — small thing, but it's the kind of typo that's awkward to
  fix once external users script against it.

**Deliverable:** `pip install -e .` gives a working `datorum` command,
CI is green, repo is presentable.

---

## 4. Phase 2 — Domain data model

Currently `__main__.main()` loads `domains.json` into a raw dict and walks
it by hand three levels deep with a `match`/loop. This is the thing every
later phase (CLI editing, scraper schemas, agent) needs to not be built on
top of.

- `datorum/domains/models.py`: `Source`, `Topic`, `Domain` as pydantic
  models (mirroring the existing JSON shape exactly — no field changes yet).
- `datorum/domains/repository.py`: `DomainsRepository` with
  `load()`, `save()` (atomic write: temp file + rename, so a crash mid-write
  can't corrupt `domains.json`), `get_source(id)`, `add_domain/topic/source`,
  `remove_*`, plus validation (unique slugs/ids, scraper name exists in the
  registry).
- Swap `__main__.py`'s inline traversal for calls to this repository.
  Behavior-identical — covered by the phase-0 tests.

**Deliverable:** all reads/writes of `domains.json` go through one class;
`scrap`/`chunk` behave exactly as before.

---

## 5. Phase 3 — Scraper parameter schemas (the decoupling groundwork)

This is the piece that most directly unblocks the "agent picks a scraper"
feature, so it's worth doing as its own phase rather than folding it into
the CLI work.

- Each scraper declares a pydantic model for its `scraper_args` instead of
  reading them as untyped `**kwargs`, e.g. `QMDScraper.Params(title, license,
  owner, repo, branch, quarto_path=None, github_token=None)`. The `extract()`
  signature becomes `extract(self, url: str, params: Params) -> ScrapedDocument`,
  with a thin `**kwargs` adapter kept temporarily at the registry boundary so
  `domains.json`'s existing dict-based `scraper_args` keep working unchanged.
- Add a classmethod every scraper implements, e.g.
  `can_handle(url: str) -> float` (0–1 confidence), so a router can shortlist
  candidates before ever calling a model — this keeps the local small model's
  job to "pick among 2-3 plausible scrapers and fill in params," not "know
  about all 7 scrapers from scratch," which matters a lot for a small model's
  reliability.
- `registry` gains a `describe()` helper that returns each scraper's name,
  docstring, and JSON-schema'd params (pydantic gives this for free) — this
  is what both the CLI (`source add`, for interactive param prompts) and the
  agent (as part of its tool/response schema) will consume.
- Update `data/domains.json` entries' `scraper_args` — no shape change
  needed, since these become the same keys, just validated now.

**Deliverable:** every scraper has a typed, introspectable parameter
contract; nothing about the CLI or the agent needs to exist yet for this to
be independently useful (better error messages, self-documenting).

---

## 6. Phase 4 — Config system: user config files instead of `.env`

- New module `datorum/config/`. Config is layered, lowest to highest
  priority: **built-in defaults → user config file → environment variables
  → CLI flags**. Env vars stay in the mix (useful for CI/containers), but
  stop being the primary interface.
- File location via `platformdirs` (handles the right XDG/AppData/Library
  path per OS) — e.g. `~/.config/datorum/config.toml` on Linux.
- **Format: TOML.** It's the standard for this kind of file in the Python
  ecosystem now (comments, native types, no YAML indentation footguns).
- Shape sketch:
  ```toml
  [general]
  data_dir = "data"

  [providers.chunker]
  base_url = "https://api.openai.com/v1"
  model = "gpt-4o-mini"
  api_key_ref = "chunker"        # points into the secret store, phase 5

  [providers.router]
  base_url = "http://localhost:11434/v1"   # local model server
  model = "qwen2.5-3b-instruct"
  api_key_ref = ""                          # local models often need none
  ```
- CLI: `datorum config init` (writes a commented template),
  `datorum config edit` (opens `$EDITOR`), `datorum config show` (prints
  resolved config with secrets masked).
- Migration path: `datorum config migrate-env` reads an existing `.env`,
  writes the equivalent `config.toml`, and pushes any `*_API_KEY` values
  into the secret store from phase 5. `.env` support stays as a fallback
  (with a one-time deprecation notice) for a release or two rather than
  breaking existing setups outright.

**Deliverable:** a real config file replaces `.env` as the primary path,
with a clean migration for anyone already using this.

---

## 7. Phase 5 — Encrypting the API keys

The config file above intentionally never holds raw keys — only an
`api_key_ref`. Actual secret storage is a pluggable backend:

- **Backend A — OS keychain**, via the `keyring` package. Delegates to
  macOS Keychain / Windows Credential Locker / a Linux Secret Service
  (GNOME Keyring, KWallet). No passphrase to manage, strongest option when
  it's available.
- **Backend B — encrypted file**, via `cryptography`'s Fernet, key derived
  from a passphrase with `scrypt`. Stored at
  `~/.config/datorum/secrets.enc`. This is the one that actually works
  headless (servers, CI, containers without a Secret Service running),
  which matters here since part of the point is running a local model —
  plausibly on a headless box.
- **Selection:** try `keyring` first; if it raises (no backend available —
  common on plain Linux servers) fall back to the encrypted file
  automatically, with a one-line notice so it's not silent. Overridable
  explicitly via `[secrets] backend = "keyring" | "file"` in the config.
- Passphrase for the file backend: prompted interactively (`getpass`, never
  echoed, never logged) or read from `DATORUM_MASTER_PASSWORD` for
  non-interactive use. Document clearly that the latter only moves the
  secret one level up (env var instead of file) — it's for CI convenience,
  not a claim of extra security.
- CLI: `datorum secrets set <provider>`, `datorum secrets rm <provider>`,
  `datorum secrets list` (names only, never values). `InferenceFactory`
  resolves `api_key_ref` through this module instead of reading
  `*_API_KEY` out of `GeneralConfig` directly.
- Guardrail: a small `SecretStr`-style wrapper (pydantic already has one)
  used anywhere a key passes through the code, so it can't accidentally
  land in a `print()`, log line, or traceback.

**Deliverable:** no API key ever sits in plaintext on disk by default;
`InferenceFactory` is the only thing that ever sees a resolved key, and
only in memory.

---

## 8. Phase 6 — CLI expansion

With phases 2–5 in place, the CLI itself is mostly wiring.

- Switch from `argparse` to `typer` — subcommand groups map cleanly onto
  the domain/topic/source/provider/config/secrets structure, and it
  generates `--help` from the same type hints used elsewhere in the
  codebase.
- Command groups:
  - `datorum scrape <source-id>` / `datorum chunk <source-id>` (existing
    behavior, renamed).
  - `datorum domain {add,list,remove}` / `datorum topic {add,list,remove}`
  - `datorum source {add,edit,remove,list}` — `add`/`edit` use each
    scraper's declared param schema from phase 3 to validate input (and
    can prompt interactively for missing required fields).
  - `datorum provider {add,edit,remove,list}` — manage the
    `[providers.*]` blocks in config.
  - `datorum config {init,edit,show,migrate-env}`
  - `datorum secrets {set,rm,list}`
- All mutating commands go through `DomainsRepository`'s atomic save —
  no more hand-edited `domains.json`.

**Deliverable:** everything that currently requires opening
`data/domains.json` in a text editor is a CLI command.

---

## 9. Phase 7 — Agent scaffolding (seams only, not the agent itself)

You mentioned this is prep for the *next* feature, not this refactor — so
this phase is deliberately just the interfaces, not a working router:

- `datorum/agent/router.py`: a `ScraperRouter` protocol —
  `route(url: str, task_context: str) -> RouterDecision`, where
  `RouterDecision` is a pydantic model (`scraper: str`, `params: dict`,
  `confidence: float`, `reasoning: str`). This reuses the existing
  `InferenceRequest.response_schema` structured-output support already in
  `providers/inference.py` — no new plumbing needed there.
- The router's prompt-building step calls `registry.describe()` (phase 3)
  filtered by each scraper's `can_handle(url)` score, so the local model
  is only ever asked to choose among a short, relevant list — important
  for a small local model's accuracy.
- Wire the `router` provider profile (added in phase 4's config sketch)
  through `InferenceFactory`, pointed at a local OpenAI-compatible
  endpoint (Ollama / llama.cpp server / vLLM — whichever you land on for
  serving the small model).
- `datorum route <url>` CLI command that runs routing and prints the
  decision without executing the scrape — lets you iterate on the router
  prompt/model in isolation before it's wired into `scrape`.

**Deliverable:** the seam between "decide which scraper + params" and
"run the scraper" is a real interface, ready for the router's actual logic
to be built against next — without this refactor having to solve the
agent's prompt design now.

---

## 10. Phase 8 — Code quality pass (continuous, closed out here)

Some of this happens incidentally in earlier phases; this phase is the
sweep to make it consistent everywhere:

- `print()` → `logging`, with `-v/--verbose` on the CLI controlling level.
- Exception hierarchy: `DatorumError` base, `SourceNotFoundError`,
  `ScraperError`, `ConfigError`, `SecretBackendError` — replacing the bare
  `Exception`/`ValueError` raises scattered today.
- Docstring pass for public classes/methods (the scrapers already have
  good docstrings in places — `ArchiveOrgScraper`, `QMDScraper` — extend
  that standard to everything).
- `mypy` in CI once the phase-3 typed params make the codebase mostly
  typed anyway.
- Expand the phase-0 test suite to cover the new modules
  (`DomainsRepository`, config layering, secret backends, CLI commands via
  Typer's `CliRunner`).

**Deliverable:** consistent logging/errors/typing/tests across the whole
package, not just the new modules.

---

## Suggested order

Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7, with phase 8 threaded through each
phase as it lands (not saved entirely for the end) rather than done as one
giant cleanup pass. Phases 4 and 5 could swap if you'd rather see key
encryption solved before touching the config format, but config needs to
exist first for `api_key_ref` to have somewhere to live, so 4-then-5 is the
cleaner order.

---

## Open decisions worth your input before starting

1. **License** — MIT vs Apache-2.0 (leaning Apache-2.0 for the patent
   grant, but it's your call).

   > Assume Apache-2.0

2. **Config format** — plan assumes TOML; YAML is the alternative if you
   have a preference.

   > Assume YAML

3. **CLI framework** — plan assumes `typer`; `click` directly is the
   alternative if you'd rather avoid the extra dependency layer typer adds
   over click.

   > Assume `typer`

4. **Secret backend default** — plan assumes keyring-first with encrypted-file
   fallback; if you know this will mostly run headless, defaulting straight
   to the encrypted-file backend might be simpler and more predictable.

   > This should be optional and configurable, with the encrypted-file as the default option

5. **Local model server** for the router provider — Ollama, llama.cpp's
   server, vLLM, or something else? This only affects the `[providers.router]`
   example in phase 4 and doesn't block any other phase.

   > This should be transparent, any OpenAI compatible endpoint should be compatible.

None of these block starting Phase 0 — happy to proceed with the defaults
above and adjust later if you'd rather decide as we go.