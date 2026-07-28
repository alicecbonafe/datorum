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

## 5. Phase 3 (marked for review) — Scraper parameter schemas (the decoupling groundwork)

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

## 6. Phase 4 (w/ phase 6) — Config system: user config files instead of `.env`

- New module `datorum/config/`. Config is layered, lowest to highest
  priority: **built-in defaults → user config file → environment variables
  → CLI flags**. Env vars stay in the mix (useful for CI/containers), but
  stop being the primary interface.
- File location via `platformdirs` (handles the right XDG/AppData/Library
  path per OS) — e.g. `~/.config/datorum/config.yaml` on Linux.
- **Format: YAML** (decided).
- Shape sketch:
  ```yaml
  general:
    data_dir: "data"

  providers:
    chunker:
      base_url: "https://api.openai.com/v1"
      model: "gpt-4o-mini"
      api_key_ref: "chunker"        # points into the secret store, phase 5

    router:
      base_url: "http://localhost:11434/v1"   # any OpenAI-compatible endpoint
      model: "qwen2.5-3b-instruct"
      api_key_ref: ""                          # local models often need none
  ```
- CLI: `datorum config init` (writes a commented template),
  `datorum config edit` (opens `$EDITOR`), `datorum config show` (prints
  resolved config with secrets masked).
- Migration path: `datorum config migrate-env` reads an existing `.env`,
  writes the equivalent `config.yaml`, and pushes any `*_API_KEY` values
  into the secret store from phase 5. `.env` support stays as a fallback
  (with a one-time deprecation notice) for a release or two rather than
  breaking existing setups outright.

**Deliverable:** a real config file replaces `.env` as the primary path,
with a clean migration for anyone already using this.

---

## 7. Phase 5 (marked for review) — Encrypting the API keys

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
- **Selection (decided): encrypted file is the default backend**, since
  headless use (a local model server, CI, containers) is the common case
  here and shouldn't depend on a Secret Service being available. `keyring`
  is available as an explicit opt-in, configurable via
  `secrets.backend: "file" | "keyring"` in the config — no silent
  auto-detection/fallback between the two.
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
    `providers:` block in config.
  - `datorum config {init,edit,show,migrate-env}`
  - `datorum secrets {set,rm,list}`

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
  through `InferenceFactory`. This stays transparent to whichever server
  hosts the local model (decided) — `InferenceFactory` only needs a
  `base_url` pointing at any OpenAI-compatible endpoint (Ollama, llama.cpp
  server, vLLM, or otherwise), with no server-specific code in Datorum.
- `datorum route <url>` CLI command that runs routing and prints the
  decision without executing the scrape — lets you iterate on the router
  prompt/model in isolation before it's wired into `scrape`.

**Deliverable:** the seam between "decide which scraper + params" and
"run the scraper" is a real interface, ready for the router's actual logic
to be built against next — without this refactor having to solve the
agent's prompt design now.

---

## 10. Phase 8 — Code quality pass (continuous)

**Checklist**

- [ ] Application logging
- [ ] Public API docstrings
- [ ] Test cases
- [ ] Lint

---

## 11. Phase 9 — Publishing & OSS release

Everything up to here can happen in a private repo. This phase is what
actually makes Datorum public, so it comes last rather than in phase 1.

- **Canonical repo on Codeberg, CI via Codeberg's hosted Woodpecker
  instance** (`.woodpecker.yml`): lint (`ruff`), format check, `pytest`, on
  PR + push. linux/amd64 only, which is fine for a pure-Python CLI. Chosen
  over GitHub Actions for alignment with a community-driven, donation-funded
  forge rather than a platform subject to one company's commercial
  direction — no access-request delay since you're already a Codeberg user.
- **Read-only mirror to GitHub** (Codeberg's push-mirror feature, or a
  scheduled `git push --mirror`), to keep the project discoverable where
  most contributors/search traffic still are, without moving issues/PRs/CI
  off Codeberg. GitHub Issues/PRs left disabled on the mirror so
  contribution stays funneled to Codeberg.
- **Funding**: Liberapay as the primary donation link, backed by a
  Brazilian PayPal account (Liberapay doesn't support Stripe payouts to
  Brazil, only PayPal). Concretely:
  - Open a PayPal Brasil account under your CPF, link it as the payout
    method on your Liberapay profile.
  - Register a Pix key on that PayPal account — PayPal settles your
    balance to your linked Brazilian bank account via Pix (or TED),
    automatically, daily.
  - Add a `FUNDING.md` (or a "Support" section in the README, written now
    that the page exists) linking to the Liberapay page.
- Rest of the OSS-release checklist: tag `v1.0.0`, publish to PyPI (trusted
  publishing from CI once it's on Codeberg/Woodpecker, or a manual `twine
  upload` for the first release), list Datorum on relevant awesome-lists.

**Deliverable:** Datorum is public on Codeberg with green CI, discoverable
via a GitHub mirror, installable from PyPI, and has a working donation
link that actually reaches your bank account.

---

## Suggested order

Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 9, with phase 8 threaded through each
phase as it lands (not saved entirely for the end) rather than done as one
giant cleanup pass. Phases 4 and 5 could swap if you'd rather see key
encryption solved before touching the config format, but config needs to
exist first for `api_key_ref` to have somewhere to live, so 4-then-5 is the
cleaner order. Phase 9 is last on purpose — publishing only makes sense
once everything else is done.

---

## Decisions made

These were open questions in an earlier draft; all are now resolved and
reflected in the relevant phases above.

1. **License** — Apache-2.0 (phase 1).
2. **Config format** — YAML (phase 4).
3. **CLI framework** — `typer` (phase 6).
4. **Secret backend default** — encrypted file by default, `keyring`
   available as an explicit, configurable opt-in (phase 5).
5. **Local model server** for the router provider — no assumption baked in;
   any OpenAI-compatible endpoint works via `base_url` (phase 7).