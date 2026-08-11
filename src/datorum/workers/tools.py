import json
from pathlib import Path
from typing import Any, Optional, Literal

from pydantic import BaseModel

from ..context import DocumentContext, DocumentReference
from ..exceptions import ToolWorkerException, MissingContextException
from ..inference import ChatHistory, AssistantMessage, ToolMessage
from ..tooling import ToolBoxSetUp, get_toolbox_definition
from .base import JobStatus, Job, Worker


class ToolWorker(Worker):
    required_documents: list[str] = ["tool_params", "tool_result"]

    def __init__(self, job: Job, toolbox: ToolBoxSetUp, tool_name: str):
        super().__init__(job=job)
        self.toolbox = toolbox
        self.tool_name = tool_name

    async def work(self):
        await self.job.update_status(JobStatus.WORKING, "Collecting toolbox resources")

        toolbox_def = get_toolbox_definition(self.toolbox.toolbox_name)
        if self.tool_name not in toolbox_def.tools:
            raise ToolWorkerException(f"Tool '{self.tool_name}' not found in ToolBox '{toolbox_def.name}'")
        # tool_def = toolbox_def.tools[self.tool_name]
        toolbox = toolbox_def.create_toolbox()

        for field_name, field in toolbox_def.context_fields.items():
            if field.content_type.endswith("-output"):
                continue

            if field_name not in self.toolbox.context_bindings:
                if field.required:
                    raise ToolWorkerException(f"Context field '{field_name}' is required for ToolBox '{toolbox_def.name}'")
                continue

            field_value: Any = None
            bind_id = self.toolbox.context_bindings[field_name]

            if field.content_type.startswith("domain-"):
                context: Optional[DocumentContext] = None
                for ctx in self.job.contexts.values():
                    if ctx.knows_domain(bind_id):
                        context = ctx
                        break
                
                if context is None:
                    if field.required:
                        raise ToolWorkerException(f"Required domain '{bind_id}' not found")
                    continue

                if field.content_type == "domain-path":
                    field_value = context.get_domain_path(bind_id)
                elif field.content_type == "domain-metadata":
                    field_value = context.get_domain_metadata(bind_id)

            else:
                document: Optional[DocumentReference] = None
                for ctx in self.job.contexts.values():
                    document = ctx.get_document(bind_id)
                    if document:
                        break
                
                if not document:
                    if field.required:
                        raise ToolWorkerException(f"Required document '{bind_id}' not found")
                    continue

                if field.content_type == "document-path":
                    field_value = document.doc_path
                elif field.content_type == "document-metadata":
                    field_value = document.metadata
                elif not document.doc_path.exists():
                    raise ToolWorkerException(f"Required document '{bind_id}' not found")
                elif field.content_type.startswith("model"):
                    field_value = document.load()
                elif field.content_type.startswith("text"):
                    field_value = document.doc_path.read_text(encoding="utf-8")
                elif field.content_type.startswith("bytes"):
                    field_value = document.doc_path.read_bytes()

            setattr(toolbox, field.attr_name, field_value)

        tool_params_doc = self.job.context.documents["tool_params"]
        tool_result_doc = self.job.context.documents["tool_result"]

        tool_params = None
        tool_call_id = "no-id"
        chat_history: Optional[ChatHistory] = None
        if tool_params_doc.doc_path.exists():
            if tool_params_doc.doc_model == "chat-history":
                chat_history = tool_params_doc.load()
                assistant_message: AssistantMessage = chat_history.messages[-1]
                if not assistant_message.tool_calls:
                    raise ToolWorkerException(f"Agent's tool call is empty")
                for tool_call in assistant_message.tool_calls:
                    if tool_call.function.name == f"{self.toolbox.id}.{self.tool_name}":
                        tool_params = json.loads(tool_call.function.arguments)
                        tool_call_id = tool_call.id
                        break
            else:
                tool_params = tool_params_doc.load()

        await self.job.update_status(JobStatus.WORKING, "Starting tool")

        output = await toolbox.run_tool(
            tool_name = self.tool_name,
            params = tool_params
        )

        await self.job.update_status(JobStatus.WORKING, "Saving results")
        if tool_result_doc.doc_model == "chat-history":
            if chat_history is None or tool_result_doc.doc_path != tool_params_doc.doc_path:
                if tool_result_doc.doc_path.exists():
                    chat_history = tool_result_doc.load()
                else:
                    chat_history = ChatHistory()

            output_text: str
            if isinstance(output, str):
                output_text = output
            elif isinstance(output, dict):
                output_text = json.dumps(
                    output, indent=2, ensure_ascii=False)
            elif isinstance(output, BaseModel):
                output_text = output.model_dump_json(
                    indent=2, ensure_ascii=False)
            else:
                output_text = str(output)
            chat_history.messages.append(ToolMessage(
                content=output_text,
                tool_call_id=tool_call_id,
            ))

            tool_result_doc.save(chat_history)
        else:
            tool_result_doc.save(output)
