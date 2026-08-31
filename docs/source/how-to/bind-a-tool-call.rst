================
Bind a tool call
================

This extends :doc:`bind-a-resource` with what actually happens to the
``tool_params``/``tool_result`` bindings -- and to the toolbox's own
``ContextField``/``ResourceField`` attributes -- once ``ToolWorker`` picks up
a job. Confirmed against ``src/datorum/tooling/worker.py`` and
``src/datorum/tooling/registry.py``.

The ``toolbox_setup`` binding
------------------------------

A tool call is selected by a single resource binding:

.. code-block:: bash

   -r toolbox_setup=toolbox_setup(SETUP_ID.TOOL_NAME)

``SETUP_ID`` is the ID of a :py:class:`~datorum.ToolBoxSetUp` registered in
your ``ToolKit`` (``toolkit.toolboxes`` in settings) -- not necessarily the
same string as the toolbox class's own registered ``name``, though they're
often equal. ``TOOL_NAME`` is one of that setup's ``tools_enabled``. The
``toolbox_setup`` factory itself is only available once a ``ToolWorker`` has
been constructed -- it's registered in ``ToolWorker.__init__``, not present
as a static, always-available factory.

What ``tool_params``/``tool_result`` actually do
----------------------------------------------------

Both are required on every tool call -- ``ToolStep`` has no default for
either, and ``ToolWorker.work`` looks each one up unconditionally.

* ``tool_params`` is resolved to a document, loaded, and handed to the tool:

  * If the tool method takes parameters, the loaded value is matched against
    the tool's inferred (or explicit) params model and passed in -- as a
    single model argument if the method has one parameter typed as a
    ``BaseModel`` subclass, otherwise unpacked as keyword arguments.
  * If the tool method takes **no** parameters, it has no params model at
    all, and the loaded document is read but then discarded -- the method is
    always called with zero arguments. It is safe (and common) to point
    ``tool_params`` at an otherwise-unused scratch document for such tools;
    its content is never inspected.

* ``tool_result`` is resolved to a document and the tool's return value is
  saved to it. ``None``, ``str``, ``dict``, and ``BaseModel`` return values
  are all handled; anything else falls back to ``str(result)``.

The ``ChatHistory`` special case
-----------------------------------

If ``tool_params`` resolves to a document whose ``doc_model`` is
``"chat-history"``, the Worker doesn't load it as a flat params document --
it pulls the parameters straight out of the tool call recorded in the
latest ``AssistantMessage``. Symmetrically, if ``tool_result`` resolves to a
``ChatHistory``, the result isn't overwritten wholesale; a ``ToolMessage``
carrying the result is appended to the existing message list instead. This
is exactly how an agent-driven tool call (see below) reuses its own
``chat_history`` binding for both ``tool_params`` and ``tool_result`` --
and it's available to you too, for any ``ToolStep`` where that's the shape
you want.

How this interacts with an ``AgentStep``
------------------------------------------

You never write ``tool_params``/``tool_result``/``toolbox_setup`` bindings
for a tool a model calls mid-conversation -- ``AgentWorker`` builds them
for you, automatically, once per tool call the model makes:

* ``tool_params`` and ``tool_result`` are both bound to the *same* document
  as the ``AgentStep``'s own ``chat_history`` binding (relying on the
  ``ChatHistory`` special case above).
* ``toolbox_setup``'s selector is the tool call's function name verbatim --
  which is why a tool exposed to a model always needs the
  ``SETUP_ID.TOOL_NAME`` form in ``AgentRole.tools_enabled``: that's the
  exact string the model is given as the callable function's name, and the
  exact string used to route the call back.

All you configure, for tool use by a model, is ``tools_enabled``,
``tool_choice``, and ``tool_max_iter`` on the role. If ``tools_enabled`` is
empty, no ``tools``/``tool_choice`` fields are even sent in the inference
request.

The toolbox's own fields: job overrides, then the setup
------------------------------------------------------------

Separately from ``tool_params``/``tool_result``, every ``ContextField`` and
``ResourceField`` declared on the toolbox class itself (e.g. ``domain``,
``interactive`` in the Doc Search Agent tutorial) is resolved once per tool
call, in this order:

#. A binding with a matching ``field_id`` in the *job's own*
   ``context_bindings``/``resource_bindings`` -- i.e. a ``ToolStep``'s
   ``custom_context``/``custom_resources``, or a CLI ``-c``/``-r`` flag on
   ``datorum run tool``.
#. Falling back to the matching binding in the ``ToolBoxSetUp``'s own
   ``context_bindings``/``resource_bindings``.
#. If neither has one and the field is required, the call fails before the
   tool ever runs.

This is what lets a single ``ToolBoxSetUp`` serve as the normal, shared
wiring for a toolbox, while individual pipeline steps override just the
field they need to differ on for that one call.