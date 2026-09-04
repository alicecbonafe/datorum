====================================
Implementing context builder toolbox
====================================

This next toolbox isn't designed to be called by agents, although there is
technically nothing preventing it. The goal here is to prepare the Markdown
so the user can select from the available files; assemble the chat history
based on the next model to be called; and finally extract the model's response
and append it into the Markdown for the user.

Bindable fields
===============

In addition to the path to the domain and the Markdown document, we also need
access to the chat history used by the agents and to the two roles, from which
we will extract the ``system_instructions``. These roles are available as a
runtime resource.

.. code-block:: python
    from pathlib import Path
    from typing import Any

    import datorum

    @datorum.toolbox(name="context_builder")
    class ContextBuilderToolBox:
        domain: Path | None = datorum.ContextField(
            context_bind_type="domain-path",
            required=True,
        )
        interactive: datorum.MarkdownDocument | None = datorum.ContextField(
            context_bind_type="model",
            required=True,
        )
        searcher_role: datorum.AgentRole | None = datorum.ResourceField(
            required=True,
        )
        answerer_role: datorum.AgentRole | None = datorum.ResourceField(
            required=True,
        )
        agent_chat: datorum.ChatHistory | None = datorum.ContextField(
            context_bind_type="model",
            required=True,
        )

Tool declarations
=================

These tools don't really need any parameters, because all relevant context are
already binded. On the other hand, returning a ``dict[str, Any]`` is useful to
change pipeline flow path and to manually inspect the results.



.. code-block:: python

    @datorum.toolbox(name="context_builder")
    class ContextBuilderToolBox:

        # (bindable fields)

        @datorum.tool()
        def scaffold_selection(self) -> dict[str, Any]:
            """List the files under ``domain`` and scaffold the selection checklist.

            Writes a ``files`` map (filename -> ``False``) into ``interactive``'s
            frontmatter so the user has one checkbox per file to flip on. The
            Markdown content -- which carries the template's placeholder prompt
            text -- is left untouched; the user edits that placeholder directly
            during the HITL pause.
            """
            ...

        @datorum.tool()
        def build_chat_history(self) -> dict[str, Any]:
            """Build ``agent_chat`` from the user-edited selection document.

            If chat history is empty and the user selected at least one searchable file,
            prepare chat history for the searcher.
            If there're no searchable files selected, or if the first model already made
            the tool calls, prepare chat history for the final answer.
            """
            ...

        @datorum.tool()
        def extract_answer(self) -> dict[str, Any]:
            """Extract the final answer from the chat history and append it to the interactive markdown."""
            ...

See the :download:`full implementation here </examples/doc-search-agent/context_builder.py>`.

Configuring
===========

Now let's create the toolbox setup and add the Python code to the custom registry.

.. code-block:: yaml
    # (...)
    toolkit:
      toolboxes:
        # (...)
        context_builder:
          id: context_builder
          toolbox_name: context_builder
          tools_enabled:
          - scaffold_selection
          - build_chat_history
          - extract_answer
          context_bindings:
          - field_id: domain
            binded_id: quirky_tech_specs
            context: files
            context_bind_type: domain-path
            local: false
          - field_id: interactive
            binded_id: selection
            context: docs
            context_bind_type: model
            local: true
          - field_id: agent_chat
            binded_id: chat
            context: docs
            context_bind_type: model
            local: true
          resource_bindings:
          - field_id: searcher_role
            factory_name: agent_role
            selector: searcher
          - field_id: answerer_role
            factory_name: agent_role
            selector: answerer
    # (...)
    custom_registry:
    - doc_search_toolbox.py
    - context_builder.py
    api_keys:
      lmstudio: lmstudio

Testing
=======

By default, agent roles are not loaded for tool runs. So, we need to tell the
CLI to load them before running the tools. This can be accomplished by adding
the ``-a`` (or ``--load-agents``) flag. Let's see how the tool will prepare the
markdown for human interaction.

.. code-block:: bash
    datorum run tool context_builder.scaffold_selection docs:empty _docs:tool-response --load-agents

This creates the ``selection.md`` file inside the local context, with all
searchable files listed in the frontmatter


