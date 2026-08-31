===============
Bind a resource
===============

Use the ``--bind-context`` (``-c``) and ``--bind-resource`` (``-r``) flags with
``datorum run tool`` and ``datorum run agent`` to connect job fields to context
documents or runtime resources.

Context bindings
----------------

A context binding connects a job field to a document (or a document’s metadata or
path) stored in a :py:class:`~datorum.DocumentContext`.

.. code-block:: bash

   -c FIELD=TYPE([CONTEXT:]ID)

* ``FIELD`` — the name of the field the worker expects (e.g. ``input``,
  ``output``, ``params``).
* ``TYPE`` — a :py:class:`~datorum.ContextBindType` value (see below).
* ``CONTEXT`` — optional name of the shared context to resolve from. If omitted,
  the binder searches all registered shared contexts.
* ``ID`` — the document identifier (dotted path) inside the context.

A leading underscore on ``TYPE`` (e.g. ``_text-input``) marks the binding as
**local** instead of shared. Local bindings are resolved against the job’s
local context (a copy of the shared document) and are written back to that
local copy.

Available ``ContextBindType`` values
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

============================= ===================================================
Value                         Meaning
============================= ===================================================
``model``                     Read/write the document as a Pydantic model
``model-input``               Read-only model access
``model-output``              Write-only model access
``text``                      Read/write the document as raw text
``text-input``                Read-only text access
``text-output``               Write-only text access
``bytes``                     Read/write the document as raw bytes
``bytes-input``               Read-only bytes access
``bytes-output``              Write-only bytes access
``document-path``             Filesystem path to the document (read-only)
``document-metadata``         Document metadata dict (read/write)
``domain-path``               Filesystem path to a domain folder (read-only)
``domain-metadata``           Domain metadata dict (read/write)
============================= ===================================================

Shared vs. local bindings
~~~~~~~~~~~~~~~~~~~~~~~~~

* **Shared** bindings read from and write directly to the shared context.
* **Local** bindings (prefixed with ``_``) operate on a per-job local copy of
  the document. This allows jobs to modify documents without affecting the
  shared context. Local bindings require that the job provides a
  ``local_context_id`` (automatically set by ``datorum run``).

Example: binding a context field
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following command binds the job field ``params`` to the document
``config/settings`` inside the shared context ``my_ctx``, using the
``model-input`` type (read-only model access):

.. code-block:: bash

   datorum run tool my_toolbox.my_tool \
     -c params=model-input(my_ctx:config/settings)

Resource bindings
-----------------

A resource binding connects a job field to a runtime resource (e.g. an API key,
a database connection) provided by a registered factory.

.. code-block:: bash

   -r FIELD=FACTORY(SELECTOR)

* ``FIELD`` — the name of the field the worker expects.
* ``FACTORY`` — the name of a registered resource factory (e.g. ``api_key``).
* ``SELECTOR`` — a string passed to the factory to identify which specific
  resource to return (e.g. the environment variable name for an API key).

Example: binding a resource field
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following command binds the job field ``api_key`` to the resource produced
by the ``api_key`` factory, using the selector ``OPENAI_API_KEY``:

.. code-block:: bash

   datorum run agent my_role chat_history.md \
     -r api_key=api_key(OPENAI_API_KEY)