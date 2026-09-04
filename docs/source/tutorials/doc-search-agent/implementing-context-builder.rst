====================================
Implementing context builder toolbox
====================================



Bindable fields
===============


.. code-block:: python
    from pathlib import Path
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
