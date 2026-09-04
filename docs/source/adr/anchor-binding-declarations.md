# Anchors: a shared binding-declaration pattern

Status: Draft -- design decisions finalized, implementation not started

## Problem

Datorum has three places that declare what bindings a piece of code needs,
and they don't agree with each other:

* **`Worker.required_context_binds` / `required_resource_binds`**
  (`work/worker.py`) -- a flat `ClassVar[list[str]]` of field IDs. No type
  information, no way to express "required." `AgentWorker.work()` has to
  hand-check `chat_bind.context_bind_type != ContextBindType.model` inline
  because the declaration can't carry that.
* **`ContextField` / `ResourceField`** (`tooling/registry.py`, based on
  `BaseToolBoxField`) -- a real declaration: `context_bind_type`,
  `required`, `description`, `attr_name`. Scoped to toolboxes only, despite
  nothing about it being toolbox-specific.
* **Pipeline step fields** (`ToolStep`, `AgentStep`, etc. in
  `plumbing/settings.py`) -- plain typed Pydantic fields
  (`tool_params: ContextBind`, `inference_provider: ResourceBind`, ...).
  Required-ness is already fully expressed by whether the field has a
  default. This one isn't actually a gap.

Two concrete symptoms, not hypothetical ones:

1. `Worker.start()` is the only place `required_context_binds`/
   `required_resource_binds` are checked, and nothing in the codebase
   calls `start()` -- the CLI and `PipelineWorker`'s step delegation both
   call `run()` directly. The requirement declarations are currently
   unenforced everywhere.
2. Required-field checking for toolboxes is already duplicated
   independently in two places: `ToolWorker.work()`'s field-resolution
   loop, and `ToolBoxDefinition.create_toolbox()`'s `run_tool` closure.
   Same rule, two call sites, two different exception types, no shared
   source of truth.

Separately, `BaseToolBoxField` no longer describes what the class is, and
collides in name with `pydantic.Field`, which every settings class in the
project already uses constantly for something unrelated.

**This design supersedes the two issues originally scoped separately for
alpha 3** (making `ToolStep.tool_params`/`tool_result` optional for
zero-argument tools, and making `AgentStep.inference_provider` optional).
Both become direct, automatic consequences of adopting real anchor-based
required-ness -- not separate work.

## Non-goals

Earlier drafts of this design considered a `Bindable` protocol (for
Workers and toolboxes to implement), a `BindingSource` protocol (for
pipeline steps and jobs to implement), and a new `BindingRequirement`
data class. All three are dropped:

* No new protocol is needed. Validation doesn't need to be polymorphic --
  it's one function operating on plain data (a list of anchors, a list of
  concrete bindings), not a method every consumer implements differently.
* `BindingSource` was solving an already-solved problem: `Job.
  context_bindings`/`resource_bindings`, and `PipelineWorker`'s existing
  per-step-type binding lists (e.g. `[current_step.tool_params,
  current_step.tool_result, *current_step.custom_context]`), already
  flatten a step's concrete bindings into exactly the shape validation
  needs. A protocol here would just be naming something the code already
  does inline.
* `BindingRequirement` would have duplicated `ContextField`/
  `ResourceField` field-for-field. The fix is generalizing what already
  exists, not adding a parallel type next to it.

## Proposed design

### Rename and relocate

`BaseToolBoxField` -> `Anchor`; `ContextField` -> `ContextAnchor`;
`ResourceField` -> `ResourceAnchor`. Move from `tooling/registry.py` into
`binding/` (e.g. `binding/anchors.py`) -- the concept isn't
toolbox-specific and shouldn't live under `tooling/`.

```
Anchor                      # was BaseToolBoxField
├── ContextAnchor           # was ContextField
└── ResourceAnchor          # was ResourceField
```

This is a public API rename (`datorum.ContextField`/`datorum.ResourceField`
are used directly in every toolbox class body) and is explicitly in scope
for alpha 3, along with the test and doc updates it requires -- see
"Alpha 3 scope" below.

### Workers declare anchors the same way toolboxes do

A Worker subclass declares its needs declaratively, in the class body,
exactly like a toolbox:

```python
class AgentWorker(Worker):
    chat_history: ChatHistory = ContextAnchor(context_bind_type="model", required=True)
    agent_role: AgentRole = ResourceAnchor(required=True)
```

This replaces `required_context_binds`/`required_resource_binds` with a
single `anchors: ClassVar[list[Anchor]]`, collected automatically.

**Why this needs more than copying the toolbox mechanism verbatim.**
Toolbox instances are recreated fresh per call --
`ToolBoxDefinition.create_toolbox()` instantiates a new object on every
single `work()` invocation -- so `setattr(instance, attr_name, value)` is
safe; nothing else shares that instance. Workers are the opposite: built
once, persisting across every job, and `start()`'s fire-and-forget design
means multiple jobs can genuinely be in flight concurrently against the
same Worker instance. Setting resolved values as plain instance attributes
would let concurrent jobs stomp on each other's values through shared
state.

**Resolution: `__init_subclass__` + `property` + `ContextVar`.**

```python
class Worker(ABC):
    anchors: ClassVar[list[Anchor]] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._anchor_values = ContextVar(f"{cls.__name__}_anchor_values")
        cls.anchors = list(getattr(cls, "anchors", []))  # inherit parent anchors

        for name, value in list(vars(cls).items()):
            if isinstance(value, Anchor):
                value.attr_name = name
                cls.anchors.append(value)
                setattr(cls, name, cls._make_anchor_property(name))

    @staticmethod
    def _make_anchor_property(attr_name: str) -> property:
        def getter(self) -> Any:
            try:
                return self._anchor_values.get()[attr_name]
            except LookupError:
                raise AttributeError(
                    f"'{attr_name}' accessed outside an active run()"
                ) from None
        return property(getter)
```

```python
async def run(self, job: Job):
    problems = self.binder.validate(self.anchors, job.context_bindings, job.resource_bindings)
    if problems:
        raise WorkerRunError(...)

    resolved: dict[str, Any] = {}
    for anchor in self.anchors:
        bind = ...  # find by field_id in job.context_bindings / resource_bindings
        value = (
            await self.binder.pull_context(bind)
            if isinstance(anchor, ContextAnchor)
            else self.binder.load_resource(bind)
        )
        resolved[anchor.attr_name] = value

    token = self._anchor_values.set(resolved)
    try:
        await self.work(job)
    finally:
        self._anchor_values.reset(token)
```

`work(self, job)` keeps its exact current signature -- no second
parameter needed.

Why `property`, not `__getattr__` or `__getattribute__`:

* `__getattr__` only fires when normal attribute lookup has already
  *failed*. Since the raw `ContextAnchor`/`ResourceAnchor` instance is
  sitting directly on the class (`AgentWorker.chat_history` genuinely
  exists in the MRO), normal lookup *succeeds* and returns the anchor
  object itself -- `__getattr__` never gets called. It's the right tool
  for attributes that don't otherwise exist; this isn't that case.
* `__getattribute__` would work, by intercepting every access rather than
  only failed ones, but it's the wrong-sized tool: it fires on *every*
  attribute access for the object's entire life (`self.binder`,
  `self.jobs`, everything), and needs every internal read routed through
  `super().__getattribute__(...)` to avoid infinite recursion the moment
  it needs to check `self.anchors` itself.
* `property` is a data descriptor -- it takes precedence over instance
  `__dict__` and class attributes uniformly, so it doesn't depend on
  lookup-failure semantics at all. `__init_subclass__` replacing the raw
  declaration with a property is what makes `AgentWorker.chat_history`
  genuinely become computed-on-access, the moment the class body finishes
  executing.

Why `ContextVar` provides the isolation, precisely: isolation doesn't come
from anything the code does explicitly -- it comes from `asyncio.Task`
copying the entire context at creation. Two jobs running concurrently
against the same Worker instance are, by definition, two different tasks,
each with its own independent copy of the context from the moment it
started. `.set()` inside one task's coroutine only ever mutates that
task's copy.

`.set()` returns a `token`; `.reset(token)` in a `finally` block restores
exactly the prior value, not just "clears it" -- which is what makes
nested delegation correct. `AgentWorker.run()` sets its own values, then
directly `await`s `ToolWorker.run(tool_job)` *within the same task*
(`plumbing/worker.py` awaits sub-workers directly rather than spawning new
tasks for them), which does its own set/reset around its own anchors.
Because `reset()` restores the prior token rather than clearing to empty,
`AgentWorker`'s values are correctly back in place the instant control
returns to it.

One `ContextVar` per concrete Worker class (created in
`__init_subclass__`), not one shared across all Worker types. Not required
for correctness -- task-copying isolates regardless -- but removes a
debugging trap where two Worker subclasses sharing an `attr_name` string
could silently satisfy each other's shape if they shared one `ContextVar`.

One case this doesn't cover: `AgentWorker`'s tool-calling loop needs
*more* than a one-shot resolved value. After each delegated tool call
appends to the shared chat-history document, the next inference request
needs to see that update -- a resolved value captured once at the top of
`run()` can't reflect it. `work()` still calls
`self.binder.pull_context(chat_bind)` directly for those mid-loop
re-reads; this is safe regardless of concurrency, since `Binder` itself
holds no per-job state.

Worth noting for implementation, not required by this design: this is the
same shape as `ToolWorker.work()`'s existing toolbox-field resolution
loop (walk fields, find bind by `field_id`, resolve, keep by
`attr_name`). Once `Worker.run()` does this generically, `ToolWorker`
could plausibly call the same routine for toolbox fields instead of
duplicating it.

### Validation moves to `Binder`

```python
Binder.validate(
    anchors: list[Anchor],
    context_bindings: list[ContextBind],
    resource_bindings: list[ResourceBind],
) -> list[str]
```

Returns human-readable problem strings (empty = satisfied) rather than
raising, so a caller wanting every problem in one pass (a future
`datorum validate` command checking a whole pipeline) can collect them
all, while a caller wanting to fail fast (a Worker about to execute) does
`if problems: raise ...` around the call.

`Binder` is the right home for this, not `Worker`: it already resolves
both the local and global resource-factory registries
(`get_resource_factory`), so it can check "is `factory_name` actually
registered" in the same pass as field presence and type -- a check no
per-Worker validation could do without duplicating that access.

`Worker.run()` calls this before invoking `work()` -- not just `start()`,
which is what actually makes validation real, since `run()` is the path
both the CLI and pipeline delegation use. `start()`'s existing check can
likely be deleted outright: it already calls `run()` internally once its
task is scheduled, so it inherits the same validation for free.

### Toolbox double-check retired

`ToolWorker.work()`'s call to `Binder.validate()` (using the toolbox's own
`ContextAnchor`/`ResourceAnchor` declarations) happens before any field
resolution starts. That makes `ToolBoxDefinition.create_toolbox()`'s
duplicate required-check inside its `run_tool` closure removable -- by
the time a tool method is ever called, `ToolWorker` has already
guaranteed its required anchors are satisfied.

### Pipeline steps need no new declaration

A step's own Pydantic field signature -- which fields are required, which
are `| None = None` -- already is the complete, self-enforcing
declaration; Pydantic refuses to construct the step otherwise. This is
also what makes the two originally-separate issues trivial once this
lands: `ToolStep.tool_params`/`tool_result` and
`AgentStep.inference_provider` just become `| None = None`, no separate
mechanism required. For *static* validation of a step's bindings against
its target Worker's anchors (e.g. `datorum validate` on a pipeline config,
before any job exists), factor `PipelineWorker`'s existing per-step-type
flattening into a small reusable helper and pass the result straight to
`Binder.validate()`.

### A new `ContextBindType`: `reference`

A new kind, parallel to `model`/`text`/`bytes`: `reference`,
`reference_input`, `reference_output`, plus `is_reference()`. Resolves to
the `DocumentReference` itself -- no `.load()`/read at all -- letting the
caller decide what to do with it directly (call `.load()` for a specific
model, read raw content via `.doc_path`, inspect `.metadata`, or ignore
it).

Touch points:

* `ContextBindType.is_io()` is currently `is_model() or is_text() or
  is_bytes()` -- an explicit inclusion list, not exclusion by kind.
  `reference` needs adding here explicitly, or `pull_context()`'s
  existing "the file must already exist" guard silently won't apply to
  it.
* `Binder.pull_context()` gets one new branch:
  `if bind.context_bind_type.is_reference(): return document`.
* `Binder.push_context()` gets no `reference` branch, and should
  explicitly reject one (raise, matching how it already rejects
  `is_output()`-false binds) rather than silently no-op. A caller holding
  a live reference already has read/write access through the object
  itself (`document.save(...)`, mutating `.metadata` directly) -- there's
  nothing left for `push_context` to do on its behalf, and doing nothing
  silently would be a confusing footgun.

Scope boundary: `reference` applies to document-level binds only,
parallel to `model`/`text`/`bytes`/`document-metadata`/`document-path`
(all resolved via `find_document()`) -- not `domain-path`/
`domain-metadata`, which resolve to a `Path`/dict directly via
`find_domain_context()` and have no associated `DocumentReference` at
all.

**`reference` does not apply to `tool_params`/`tool_result`.** Datorum
needs to assume the same tool can be called from a human (CLI), an agent
(mid-conversation tool call), or a pipeline (`ToolStep`) -- so no
`DocumentReference` or `ChatHistory` is ever sent to or received from the
tool call itself; only `dict | str | None` values cross that boundary,
resolved and normalized before the call. This is already effectively true
today: the agent-driven branch of `ToolWorker.work()` always produces a
plain `dict` (`json.loads(tool_call.function.arguments)`) even though the
underlying binding is `model`-typed against a `ChatHistory` document --
the value crossing into the tool is JSON-shaped regardless of what the
document actually is, precisely because all three callers need to agree
on one shape. If a tool needs direct reference or chat-history access, it
declares that as an anchored toolbox attribute (`ContextAnchor`), not
through `tool_params`/`tool_result`.

This also closes an open question from the previous draft:
`ContextAnchor.context_bind_type` doesn't need to accept more than one
type to express the `tool_params`-can-be-`ChatHistory` case. The
guarantee that a tool receives `dict | str | None` comes from
`ToolWorker`'s own coercion, not from narrowing which bind types are
legal at the anchor level -- `chat_history`'s anchor genuinely stays
`model`-typed even though the value that eventually reaches a tool
through `tool_params` is dict-shaped.

## What this resolves

* `Worker.start()`'s validation stops being dead code.
* The duplicated toolbox required-check (`ToolWorker.work()` +
  `ToolBoxDefinition.create_toolbox()`) collapses to one call.
* `AgentWorker`'s inline `chat_bind.context_bind_type` check becomes
  declarative and reusable instead of hand-rolled.
* The two originally-separate alpha-3 issues (`tool_params`/`tool_result`
  required for zero-arg tools; `inference_provider` fallback unreachable
  in pipelines) resolve as ordinary Pydantic field changes -- no longer
  separate work, just a consequence of this design.
* `BaseToolBoxField`'s naming problem, and its collision with
  `pydantic.Field`, go away with the rename.
* Workers gain the same declarative, attribute-style ergonomics toolboxes
  already have, without the shared-instance concurrency hazard that a
  literal copy of the toolbox mechanism would have introduced.
* Callers that genuinely want raw document access (rather than forced
  deserialization) have a real, declared way to ask for it -- scoped to
  anchored attributes, not tool call boundaries.

## Open questions

* **`tool_params`/`tool_result`'s `dict | str | None` contract isn't
  currently enforced.** `ToolWorker.work()`'s non-agent-driven branch
  (`params = params_doc.load()`) passes through whatever the document's
  model deserializes to, with no coercion or check -- if the document
  happens to be some other `BaseModel` subtype, a live model instance
  reaches `toolbox.run_tool()` rather than being dict-coerced. Needs a
  coercion step: dump a `BaseModel` via `.model_dump()`, pass `dict`/
  `str`/`None` through as-is, raise clearly for anything else. The output
  side is already effectively fine -- the existing
  `str`/`dict`/`BaseModel`-via-`model_dump_json()`/fallback-`str()`
  handling when saving a tool's return value already normalizes into
  JSON-text-compatible form before writing. Flagged here, not resolved --
  deliberately deferred.
* Whether `ToolWorker.work()`'s own toolbox-field resolution loop should
  be refactored to call the same generic resolution routine `Worker.run()`
  now uses, rather than keeping its own copy. Not required for this
  design to work; worth deciding at implementation time.

## Alpha 3 scope

Renaming `ContextField`/`ResourceField` is a public API change, used
directly in every toolbox class body -- including the already-written
tutorial and how-to material. Per the decision to release all test and
doc changes for this design in alpha 3, the following need updating once
implementation lands:

* `doc_search_toolbox.py` -- `ContextField`/`ResourceField` -> `ContextAnchor`/
  `ResourceAnchor`.
* `doc_search_toolkit.yaml`, `doc_search_agents.yaml`,
  `doc_search_pipeline.yaml` -- drop the `scratch` document workaround for
  `tool_params`/`tool_result` on `list-files`/`build-history` now that
  they can be omitted outright; `inference_provider` bindings unaffected
  (still explicit, as already documented).
* `doc-search-agent.rst` -- update the "still needs a scratch document"
  framing now that the underlying requirement is gone.
* `wire-a-tool.rst` -- update to reflect the `dict | str | None` contract
  for `tool_params`/`tool_result` explicitly (currently undocumented
  entirely), and note the anchored-attribute alternative for tools
  needing direct reference/chat-history access.