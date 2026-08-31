Core concepts
=============

Datorum is built around four pillars that work together: **context**,
**binding**, **agency**, and **work**. Each is documented in full under
:doc:`../reference/index`; this page is about how they relate.

Context
-------

Context is the data an agent or pipeline reasons over.
:py:class:`~datorum.DocumentModel` and :py:class:`~datorum.DocumentHandler`
define how a given document type is represented and (de)serialized.
:py:class:`~datorum.ChatHistory` and its message types
(:py:class:`~datorum.UserMessage`, :py:class:`~datorum.AssistantMessage`,
and related classes) are the preferred, specially-treated shape, since
most agent interaction is conversational — but any registered document
type can be used the same way.

.. TIP: fill in with a short concrete snippet once one exists (e.g.
   two lines registering or loading a document). Even in an Explanation
   page, one small example gives the prose something to anchor to.

Binding
-------

Binding is how context and resources reach an agent or tool at
runtime, instead of being hardcoded into it. A
:py:class:`~datorum.ContextBind` or :py:class:`~datorum.ResourceBind`
describes *where a value comes from* — a document in a given context,
or a resource produced by a registered factory — and the
:py:class:`~datorum.Binder` resolves it at execution time. This is
also where the shared-vs-local distinction lives: most bindings are
shared across a whole project, but a binding can be scoped to a single
run so pipeline steps don't mutate shared state in place.

Agency
------

Agency is what turns bound context into an action. An
:py:class:`~datorum.AgentWorker` plays a given
:py:class:`~datorum.AgentRole` against a configured
:py:class:`~datorum.InferenceServiceProvider` — this is the layer
where Datorum's "high specialization" goal shows up most directly. An
:py:class:`~datorum.AgencyKit` groups a role, a provider, and its bound
context into one reusable, narrowly-scoped unit, rather than one
general-purpose agent handling everything.

Work
----

Work is orchestration: how tools, agents, and pipeline steps actually
get run, monitored, and composed together. Pipelines are built from
typed steps — :py:class:`~datorum.ToolStep`,
:py:class:`~datorum.AgentStep`, :py:class:`~datorum.DecisionStep`,
:py:class:`~datorum.HumanInteractionStep` — each a subclass of
:py:class:`~datorum.BasePipelineStep`, run in sequence with progress
broadcast as execution proceeds.

.. TIP: A closing ``.. glossary::`` block works well on a page like
   this — short, referenceable definitions (used elsewhere via
   ``:term:`context``` etc.) without repeating the explanation inline
   every time. Example below; expand or trim the terms as the page
   grows.

.. glossary::

   context
      The data an agent or pipeline reasons over.

   binding
      How context and resources are supplied to an agent or tool at
      runtime, rather than hardcoded.

   agency
      The layer that turns bound context into an action, via a
      role/provider pairing.

   work
      Orchestration of tools, agents, and pipeline steps as a single
      execution.