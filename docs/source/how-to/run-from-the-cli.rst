=================
Run from the CLI
=================

The ``datorum run`` command provides three subcommands for executing tools,
agents, and pipelines.

``datorum run tool``
--------------------

Execute a single tool from a toolbox.

.. code-block:: bash

   datorum run tool SELECTOR PARAMS RESULT [-c ...] [-r ...]

* ``SELECTOR`` — identifies the tool to run, in the form
  ``toolbox_setup_id.tool_name``.
* ``PARAMS`` — context binding for the tool's input parameters, in the form
  ``[CONTEXT:]DOCUMENT_ID``.
* ``RESULT`` — context binding for the tool's output result, in the form
  ``[CONTEXT:]DOCUMENT_ID``.
* ``-c`` / ``--bind-context`` — additional context bindings (see
  :doc:`bind-a-resource`).
* ``-r`` / ``--bind-resource`` — additional resource bindings (see
  :doc:`bind-a-resource`).

Example:

.. code-block:: bash

   datorum run tool my_setup.calculate params:input result:output

``datorum run agent``
---------------------

Run a single turn of an agent.

.. code-block:: bash

   datorum run agent ROLE CHAT_HISTORY [-p PROVIDER] [-c ...] [-r ...]

* ``ROLE`` — the agent role identifier (defined in :py:class:`~datorum.AgencyKit`).
* ``CHAT_HISTORY`` — context binding for the chat history document, in the form
  ``[CONTEXT:]DOCUMENT_ID``.
* ``-p PROVIDER`` / ``--provider PROVIDER`` — optional inference provider
  identifier. If omitted, the agent picks a provider from the role’s
  :py:attr:`~datorum.AgentRole.preferred_models`.
* ``-c`` / ``--bind-context`` — additional context bindings.
* ``-r`` / ``--bind-resource`` — additional resource bindings.

Example:

.. code-block:: bash

   datorum run agent assistant chat_history.md -p openai

``datorum run pipeline``
------------------------

Start a new pipeline flow or resume an existing one.

.. code-block:: bash

   datorum run pipeline (-p PIPELINE_ID | FLOW_ID) [-c/--create-only] [--non-interactive]

* ``-p PIPELINE_ID`` / ``--pipeline PIPELINE_ID`` — create a new flow from the
  named pipeline template.
* ``FLOW_ID`` — resume an existing flow by its ID (omit ``-p``).
* ``-c`` / ``--create-only`` — create the flow file without running it.
* ``--non-interactive`` — if the flow hits a paused (HITL) step, exit
  immediately instead of waiting for user input.

Streaming and status output
---------------------------

When a job streams output, chunks are printed directly to stdout as they arrive.

Status changes are printed as:

.. code-block:: text

   [UPDATE] working
   [UPDATE] paused

If a job pauses for human-in-the-loop interaction (a
:py:class:`~datorum.HumanInteractionStep`), the CLI prints the path to the
interaction file and waits for the user to edit it. Press **Enter** to continue
after editing, or **Esc** to exit.

When ``--non-interactive`` is set, the CLI exits immediately instead of waiting,
leaving the flow in a paused state for later resumption.