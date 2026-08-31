# Anchors: a shared binding-declaration pattern

Status: Draft

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

Separately: `BaseToolBoxField` no longer describes what the class is, and
its two subclasses collide in name with `pydantic.Field`, which every
settings class in the project already uses constantly for something
unrelated.

## Non-goals

Earlier drafts of this design considered a `Bindable` protocol (for
Workers and toolboxes to implement) and a `BindingSource` protocol (for
pipeline steps and jobs to implement), plus a new `BindingRequirement`
data class. All three are dropped:

* No new protocol is needed. Nothing here needs to be polymorphic --
  validation is one function operating on plain data, not a method every
  consumer implements differently.
* `Job.context_bindings`/`resource_bindings` and `PipelineWorker`'s
  existing per-step-type binding lists (e.g.
  `[current_step.tool_params, current_step.tool_result,
  *current_step.custom_context]`) already flatten a step's concrete
  bindings into the shape validation needs. Formalizing that as a
  protocol would just be naming something the code already does inline.
* `BindingRequirement` would have duplicated `ContextField`/
  `ResourceField` field-for-field. The fix is generalizing what already
  exists, not adding a parallel type next to it.

## Proposed design

**Rename and relocate.** `BaseToolBoxField` -> `Anchor`; `ContextField` ->
`ContextAnchor`; `ResourceField` -> `ResourceAnchor`. Move from
`tooling/registry.py` into `binding/` (e.g. `binding/anchors.py`) -- the
concept isn't toolbox-specific and shouldn't live under `tooling/`.

```
Anchor                      # was BaseToolBoxField
├── ContextAnchor           # was ContextField
└── ResourceAnchor          # was ResourceField
```

**`Worker` declares anchors, not strings.** Replace
`required_context_binds: ClassVar[list[str]]` /
`required_resource_binds: ClassVar[list[str]]` with a single
`anchors: ClassVar[list[Anchor]]`. `AgentWorker.anchors` would include a
`ContextAnchor(field_id="chat_history", context_bind_type=
ContextBindType.model, required=True)` -- the type check currently
hand-written inline in `work()` becomes declarative instead.

**Validation moves to `Binder`.** Add
`Binder.validate(anchors: list[Anchor], context_bindings: list[ContextBind],
resource_bindings: list[ResourceBind]) -> list[str]`, returning
human-readable problem strings (empty = satisfied) rather than raising --
so a caller wanting every problem in one pass (a future `datorum validate`
command checking a whole pipeline) can collect them all, while a caller
wanting to fail fast (a Worker about to execute) just does
`if problems: raise ...` around the call. `Binder` is the right home for
this, not `Worker`: it already resolves both the local and global
resource-factory registries (`get_resource_factory`), so it can check
"is `factory_name` actually registered" in the same pass as field
presence and type -- a check no per-Worker validation could do without
duplicating that access.

**`run()` validates, not just `start()`.** `Worker.run()` calls
`self.binder.validate(self.anchors, job.context_bindings,
job.resource_bindings)` before invoking `work()`. Since `run()` is the
path both the CLI and pipeline delegation actually use, this is what
makes validation real rather than dead code. `start()`'s existing check
can likely be deleted outright rather than kept in parallel -- it already
calls `run()` internally once the task is scheduled, so it inherits the
same validation for free.

**Toolboxes keep `ContextAnchor`/`ResourceAnchor` exactly as they declare
them today** -- no change to how a toolbox author writes
`domain: Path | None = datorum.ContextField(...)` beyond the rename.
`ToolWorker.work()`'s existing resolution loop calls the same
`Binder.validate()` before it starts resolving values, which means
`ToolBoxDefinition.create_toolbox()`'s duplicate required-check inside
`run_tool` can be deleted -- by the time a tool method is ever called,
`ToolWorker` has already guaranteed its required anchors are satisfied.

**Pipeline steps need no new declaration at all.** A step's own Pydantic
field signature -- which fields are required, which are `| None = None`
-- already is the complete, self-enforcing declaration; Pydantic refuses
to construct the step otherwise. This is also what makes issues #1 and #2
trivial once this lands: `ToolStep.tool_params`/`tool_result` and
`AgentStep.inference_provider` just become `| None = None`, no separate
mechanism required. For *static* validation of a step's bindings against
its target Worker's anchors (e.g. `datorum validate` on a pipeline
config, before any job exists), factor `PipelineWorker`'s existing
per-step-type flattening into a small reusable helper and pass the
result straight to `Binder.validate()`.

## What this resolves

* `Worker.start()`'s validation stops being dead code.
* The duplicated toolbox required-check (`ToolWorker.work()` +
  `ToolBoxDefinition.create_toolbox()`) collapses to one call.
* `AgentWorker`'s inline `chat_bind.context_bind_type` check becomes
  declarative and reusable instead of hand-rolled.
* Issues #1 (`tool_params`/`tool_result` required for zero-arg tools) and
  #2 (`inference_provider` fallback unreachable in pipelines) both
  resolve as ordinary Pydantic field changes -- no longer separate work
  from this design, just its first consequence.
* `BaseToolBoxField`'s naming problem, and its collision with
  `pydantic.Field`, go away with the rename.

## Open questions

* Whether `ContextAnchor.context_bind_type` ever needs to accept more
  than one type. `tool_params`'s `ChatHistory`-vs-plain-document duck
  typing looked at first like it might need this, but on inspection it
  doesn't: both are valid `model` bindings at the type-checking level: the
  branch between them is a runtime read of `params_doc.doc_model`, not a
  binding-validity question `Binder.validate()` should be answering.
  Worth confirming this holds once `AgentWorker`'s anchors are written
  out in full, but it's not expected to force any change to `Anchor`'s
  shape.
* Whether `Anchor`'s `attr_name` (used by toolboxes for the
  resolve-and-`setattr` step) should stay on the base class even though
  `Worker`-declared anchors have no equivalent use for it, or move down
  to `ContextAnchor`/`ResourceAnchor` specifically. Leaning toward
  leaving it on the shared base and simply unused by `Worker` -- matches
  how `description` is already optional and not always populated -- but
  worth deciding at implementation time rather than here.

## Out of scope

Renaming `ContextField`/`ResourceField` is a public API change --
`datorum.ContextField`/`datorum.ResourceField` are used directly in every
toolbox class body, including in the already-published tutorial and
how-to material (`doc_search_toolbox.py`, `bind-a-tool.rst`). That
material needs a pass once this lands; not addressed by this doc.