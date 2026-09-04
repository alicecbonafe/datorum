"""Toolbox for the "Doc Search Agent" tutorial."""

from pathlib import Path
from typing import Any

import datorum


@datorum.toolbox(name="context_builder")
class ContextBuilderToolBox:
    """Handle context files during pipeline steps.

    This toolbox is part of "Doc Search Agent" tutorial. It's meant to be
    called by pipeline steps to prepare context files to agents, HITL and
    decisions.

    Bindable fields
    ---------------

    * ``domain``: Points at a folder of documents to search.
    * ``interactive``: Contains HITL interaction, with a user-facing
      selection checklist, represented by the ``files`` key in the
      frontmatter, and the user question, within the markdown body.
    * ``searcher_role``: AgentRole used to search the files.
    * ``answerer_role``: AgentRole used to answer the question.
    * ``agent_chat``: Chat file used by the agents.
    """

    domain: Path | None = datorum.ContextField(
        context_bind_type="domain-path",
    )
    interactive: datorum.MarkdownDocument | None = datorum.ContextField(
        context_bind_type="model",
        required=True,
    )
    searcher_role: datorum.AgentRole | None = datorum.ResourceField()
    answerer_role: datorum.AgentRole | None = datorum.ResourceField()
    agent_chat: datorum.ChatHistory | None = datorum.ContextField(
        context_bind_type="model"
    )

    @datorum.tool()
    def scaffold_selection(self) -> dict[str, Any]:
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

        return {"count": len(filenames)}

    @datorum.tool()
    def build_chat_history(self) -> dict[str, Any]:
        """Build ``agent_chat`` from the user-edited selection document.

        If chat history is empty and the user selected at least one searchable file,
        prepare chat history for the searcher.
        If there're no searchable files selected, or if the first model already made
        the tool calls, prepare chat history for the final answer.
        """
        if self.agent_chat.messages:
            # Second call: searcher already called, now it's answerer turn
            if self.answerer_role.system_instructions:
                if self.agent_chat.messages[0].role == "system":
                    self.agent_chat.messages[0].content = self.answerer_role.system_instructions
                else:
                    self.agent_chat.messages.insert(0, datorum.SystemMessage(
                        role="system",
                        content=self.answerer_role.system_instructions
                    ))
            elif self.agent_chat.messages[0].role == "system":
                self.agent_chat.messages.pop(0)

            # Tell decision step who to call next
            return {"count": 0}

        else:
            # First call: extract HITL info and check if user has selected any file
            files = self.interactive.frontmatter.get("files", {})
            prompt = self.interactive.content.strip()
            count_selected = len(files)

            # Resolve the right system instructions (if exists) and create chat history
            role = self.searcher_role if count_selected else self.answerer_role
            if role.system_instructions:
                self.agent_chat.messages.append(
                    datorum.SystemMessage(role="system", content=role.system_instructions)
                )
            self.agent_chat.messages.append(datorum.UserMessage(role="user", content=prompt))

            # Tell decision step who to call next
            return {"count": count_selected}

    @datorum.tool()
    def extract_answer(self) -> dict[str, Any]:
        """Extract the final answer from the chat history and append it to the interactive markdown."""
        if not self.agent_chat.messages:
            return {"result": "Error: no messages found in chat history."}
        if self.agent_chat.messages[-1].role != "assistant":
            return {"result": f"Error: last message in chat history is '{self.agent_chat.messages[-1].role}', expected 'assistant'."}

        answer = self.agent_chat.messages[-1].content
        self.interactive.content = f"{self.interactive.content}\n\n### Agent answer\n\n{answer}"
        return {"result": "success"}
