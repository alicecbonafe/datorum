"""Toolbox for the "Doc Search Agent" tutorial."""

from __future__ import annotations

from pathlib import Path

import datorum


@datorum.toolbox(name="doc_search")
class DocSearchToolbox:
    """Tools for the Doc Search Agent tutorial pipeline.

    ``domain`` points at a folder of documents to search. ``interactive`` is
    the user-facing selection checklist (a Markdown document with a
    ``files`` frontmatter map). ``interactive_metadata`` is the sidecar dict
    Datorum stores alongside ``interactive`` -- used here to carry a plain
    ``bool`` out for the pipeline's DecisionStep, since DecisionStep requires
    a plain dict and MarkdownDocument isn't one. ``agent_role`` and
    ``agent_chat`` back the chat history construction in
    ``build_chat_history``.
    """

    domain: Path | None = datorum.ContextField(context_bind_type="domain-path")
    interactive: datorum.MarkdownDocument | None = datorum.ContextField(context_bind_type="model")
    interactive_metadata: dict | None = datorum.ContextField(context_bind_type="document-metadata")
    agent_role: datorum.AgentRole | None = datorum.ResourceField()
    agent_chat: datorum.ChatHistory | None = datorum.ContextField(context_bind_type="model")

    @datorum.tool
    def scaffold_selection(self) -> None:
        """List the files under ``domain`` and scaffold the selection checklist.

        Writes a ``files`` map (filename -> ``False``) into ``interactive``'s
        frontmatter so the user has one checkbox per file to flip on. The
        Markdown content -- which carries the template's placeholder prompt
        text -- is left untouched; the user edits that placeholder directly
        during the HITL pause.
        """
        filenames = sorted(p.name for p in self.domain.iterdir() if p.is_file())
        if self.interactive.frontmatter is None:
            # MarkdownDocument.frontmatter defaults to None, not {} -- only
            # guaranteed to be a dict if the template document already had a
            # frontmatter block when it was registered.
            self.interactive.frontmatter = {}
        self.interactive.frontmatter["files"] = {name: False for name in filenames}

    @datorum.tool
    def build_chat_history(self) -> None:
        """Build ``agent_chat`` from the user-edited selection document.

        Reads the (possibly re-checked) ``files`` map back out of
        ``interactive``'s frontmatter and the prompt text out of its
        content, then assembles the chat history: a ``SystemMessage`` from
        ``agent_role.system_instructions`` when the role sets one, followed
        by a ``UserMessage`` carrying the content text.

        As a side effect, records whether any file was selected into
        ``interactive_metadata["any_selected"]`` -- this is the plain-dict
        signal the pipeline's DecisionStep branches on next.
        """
        files = self.interactive.frontmatter.get("files", {})
        prompt = self.interactive.content.strip()

        messages: list[datorum.SystemMessage | datorum.UserMessage] = []
        if self.agent_role.system_instructions:
            messages.append(
                datorum.SystemMessage(role="system", content=self.agent_role.system_instructions)
            )
        messages.append(datorum.UserMessage(role="user", content=prompt))

        self.agent_chat = datorum.ChatHistory(messages=messages)
        self.interactive_metadata["any_selected"] = any(files.values())

    @datorum.tool
    def search(self, query: str) -> str:
        """Search the enabled files under ``domain`` for ``query``.

        "Enabled" files are the ones checked ``true`` in ``interactive``'s
        ``files`` frontmatter. Returns matching lines prefixed with their
        source filename, one per line, so the model can cite where each
        match came from. This is the only tool listed in the ``searcher``
        role's ``tools_enabled`` -- ``scaffold_selection`` and
        ``build_chat_history`` are run directly by ``ToolStep``s in the
        pipeline and never offered to a model.
        """
        files = self.interactive.frontmatter.get("files", {})
        enabled = [name for name, selected in files.items() if selected]

        matches: list[str] = []
        for name in enabled:
            path = self.domain / name
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                if query.lower() in line.lower():
                    matches.append(f"{name}: {line.strip()}")

        return "\n".join(matches) if matches else "No matches found."