================
Doc Search Agent
================

.. note::
   This tutorial demonstrates Datorum's architecture end to end: a scaffolding
   tool, a human-in-the-loop pause, a decision branch, and a two-model agent
   hand-off.

In this tutorial you'll build an agent that searches a folder of documents.
The user picks which files are in scope by editing a checklist, and a small
"searcher" model does a bounded search pass before a larger "answerer" model
writes the final response.

Register the template documents
--------------------------------

The pipeline's ``interactive`` and ``agent_chat`` fields are **local**
context binds -- each run gets its own working copy -- but a local bind
needs something to copy *from* the first time it's used. That something is
a **template**: a document you register once in a shared context, with the
shape the tool expects already in place.

Register a shared context named ``docs`` with:

* ``domain`` -- a path binding to the folder of files to search.
* ``selection`` -- a ``MarkdownDocument`` template: empty ``files``
  frontmatter and a placeholder prompt in the content, for example:

  .. code-block:: markdown

     ---
     files: {}
     ---

     <!-- Replace this line with your question about the selected files. -->

* ``chat`` -- an empty ``ChatHistory`` template.
* ``scratch`` -- an empty document used as a throwaway target for tool
  calls that don't have meaningful input or output (see below).

Write the toolbox
------------------

The toolbox holds three tools behind one set of fields: where the documents
to search live (``domain``), the user's edited selection (``interactive``),
a sidecar dict for a plain-``bool`` signal (``interactive_metadata``), the
role driving the eventual chat (``agent_role``), and the chat history itself
(``agent_chat``):

.. literalinclude:: /examples/doc-search-agent/doc_search_toolbox.py
   :language: python

A few things worth calling out:

* ``scaffold_selection`` only ever writes the ``files`` map into
  ``interactive``'s frontmatter -- it never touches the content, because the
  content already carries the template's placeholder prompt for the user to
  replace.
* ``build_chat_history`` does double duty. Its primary job is assembling
  ``agent_chat`` from the edited document. Its side effect --
  ``interactive_metadata["any_selected"]`` -- exists purely because the
  pipeline's next step, a ``DecisionStep``, requires a plain dict as input,
  and a ``MarkdownDocument`` isn't one.
* ``search`` is the only tool listed in the ``searcher`` role's
  ``tools_enabled`` (see below). ``scaffold_selection`` and
  ``build_chat_history`` are run directly by ``ToolStep``\ s and never
  offered to a model.

Wire the toolbox setup
------------------------

Registering the class with ``@datorum.toolbox`` makes it available by name;
it doesn't wire it to real documents. That wiring -- which document backs
``domain``, which backs ``interactive``, and so on -- happens **once**, in a
``ToolBoxSetUp`` under the toolkit config, and is reused by every step (and
every agent tool call) that names this setup:

.. literalinclude:: /examples/doc-search-agent/doc_search_toolkit.yaml
   :language: yaml

This is the piece easiest to get wrong by analogy with a simpler framework:
a ``ToolStep`` in the pipeline does **not** carry its own per-field binding
dict. It only points at this setup by ID (plus the tool name, joined by a
dot) and supplies ``tool_params``/``tool_result`` for that one call.

Configure two agent roles
--------------------------

Define an :py:class:`~datorum.AgencyKit` with two providers and two roles: a
cheap, bounded ``searcher`` forced to call the ``search`` tool, and a more
capable ``answerer`` that writes the final response. Give them genuinely
different ``preferred_models`` -- listing the same models for both would
defeat the point of splitting the work. Note that ``tools_enabled``,
``tool_choice``, and ``tool_max_iter`` belong on the *role*, not on the
pipeline step that uses it.

One thing worth being explicit about: ``AgentStep.inference_provider`` is a
required field with no default, and ``PipelineWorker`` always includes it
in the delegated job. ``AgentWorker`` *can* fall back to picking a provider
automatically from ``role.preferred_models`` when no ``inference_provider``
binding is present at all -- but that path is only reachable when a job is
built some other way (e.g. the CLI's ``run agent`` omitting ``-p``); inside
a pipeline, you always name the provider explicitly, as below:

.. literalinclude:: /examples/doc-search-agent/doc_search_agents.yaml
   :language: yaml

Wire the pipeline
------------------

Six steps: scaffold, pause, build the chat, decide, optionally search, then
answer. Each ``ToolStep`` names the toolbox setup and tool via
``toolbox_setup``, and still needs a ``tool_params``/``tool_result`` pair --
``ToolWorker`` always resolves both. For a zero-argument tool like
``scaffold_selection`` or ``build_chat_history``, though, whatever
``tool_params`` resolves to is loaded and then simply never used: a tool
with no parameters gets no params model, so ``ToolBox.run_tool`` calls it
with no arguments regardless of what's in the document. That's why both
point at the shared ``scratch`` document rather than at ``selection`` --
it's genuinely inert here, and reusing ``selection`` would collide with
``interactive_metadata``'s own use of that document's metadata dict:

.. literalinclude:: /examples/doc-search-agent/doc_search_pipeline.yaml
   :language: yaml

Note the ``local`` flag on every context binding -- Datorum requires it
explicitly on pipeline step bindings (no default), precisely so a rerun
never silently mutates a document another step still expects to be pristine.
``domain`` is the one binding that's genuinely ``local: false``: it's a
read-only path, so there's nothing to protect it from.

.. note::
   In future versions of the framework, the requirement for `tool_params` and
   `tool_result` will be validated based on the method signature, rather than
   being mandatory by default.

Run it
------

.. code-block:: bash

   datorum run pipeline -p doc-search-agent

The pipeline starts, runs ``list-files``, and immediately hits
``edit-selection``. You'll see:

.. code-block:: text

   [UPDATE] working
   [UPDATE] paused
   /path/to/local/context/docs/selection.md

Open that file. You'll find every file in your ``domain`` folder listed
under ``files:`` with a ``false`` next to it, and the placeholder prompt
still sitting in the content. Flip the files you want in scope to ``true``,
replace the placeholder with your actual question, save, and press
**Enter** in the terminal to resume (or **Esc** to bail out and resume the
flow later by its ``FLOW_ID``).

From here the pipeline runs unattended: ``build-history`` assembles the chat
and records whether anything was selected; ``check-selection`` branches --
straight to ``final-inference`` if you left every box unchecked, or through
``search-first`` first if you checked at least one. Either way,
``final-inference`` streams its answer to stdout, citing whatever the
searcher pass turned up.

Why two roles, not one
-----------------------

It would be simpler to give ``final-inference`` a search tool directly and
skip ``search-first`` entirely. The pipeline deliberately doesn't do that.
Forcing a smaller, cheaper model through a bounded, tool-mandated round
first -- then handing its output to a larger model as already-prepared
context -- is the pattern this framework is built around: use the small
model to do the mechanical work of narrowing down evidence, and spend the
larger model's capacity on reasoning over that evidence rather than on
finding it. The ``search-first`` / ``final-inference`` split in this
pipeline is a minimal, runnable example of that intent, not a
tutorial-specific shortcut.