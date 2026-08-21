import json
from typing import Any, ClassVar

from pydantic import BaseModel

from ..binding.binder import Binder
from ..binding.settings import (
    ContextBind,
    ResourceBind,
)
from ..context.commons.chat import (
    AssistantMessage,
    ChatHistory,
    ToolMessage,
    UserMessage,
)
from ..work.job import Job, JobStatus
from ..work.worker import Worker
from .exceptions import ToolWorkerError
from .registry import ToolBox, ToolBoxDefinition, get_toolbox_definition
from .settings import ToolBoxSetUp, ToolKit


class ToolWorker(Worker):
    required_context_binds: ClassVar[list[str]] = ["tool_params", "tool_result"]
    required_resource_binds: ClassVar[list[str]] = ["toolbox_setup"]

    def __init__(self, binder: Binder, toolkit: ToolKit):
        super().__init__(binder)
        self.toolkit: ToolKit = toolkit

        @self.binder.resource(name="toolbox_setup")
        def _toolbox_setup(selector: str | None) -> ToolBoxSetUp:
            if not selector:
                raise ToolWorkerError("Missing toolbox selector")

            _selector_parts = selector.rsplit(".", 1)
            if len(_selector_parts) != 2:
                raise ToolWorkerError(
                    f"Wrong selector format in '{selector}' (expected: 'toolbox_name.tool_name')"
                )

            toolbox_name = _selector_parts[0]
            tool_name = _selector_parts[1]
            setup = next(
                (
                    tb
                    for tb_id, tb in self.toolkit.toolboxes.items()
                    if tb_id == toolbox_name
                ),
                None,
            )
            if not setup:
                raise ToolWorkerError(f"Unknown toolbox '{toolbox_name}'")

            setup = setup.model_copy(update={"active_tool": tool_name})

            return setup

    async def work(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Collecting toolbox resources")

        setup_bind: ResourceBind = next(
            bind for bind in job.resource_bindings if bind.field_id == "toolbox_setup"
        )
        params_bind: ContextBind = next(
            bind for bind in job.context_bindings if bind.field_id == "tool_params"
        )
        result_bind: ContextBind = next(
            bind for bind in job.context_bindings if bind.field_id == "tool_result"
        )

        setup: ToolBoxSetUp = self.binder.load_resource(setup_bind)
        toolbox_def: ToolBoxDefinition = get_toolbox_definition(setup.toolbox_name)

        if setup.active_tool not in toolbox_def.tools:
            raise ToolWorkerError(
                f"Tool '{setup.active_tool}' not found in ToolBox '{setup.id}'"
            )

        if setup.active_tool not in setup.tools_enabled:
            raise ToolWorkerError(
                f"Tool '{setup.active_tool}' not enabled for ToolBox '{setup.id}'"
            )

        toolbox: ToolBox = toolbox_def.create_toolbox()

        for field_name, field in toolbox_def.context_fields.items():
            if not field.context_bind_type.is_input():
                continue

            ctx_field_bind: ContextBind | None = next(
                (
                    bind
                    for bind in job.context_bindings
                    if bind.field_id == field.attr_name
                ),
                None,
            )
            if not ctx_field_bind:
                ctx_field_bind = next(
                    (
                        bind
                        for bind in setup.context_bindings
                        if bind.field_id == field.attr_name
                    ),
                    None,
                )
                if not ctx_field_bind:
                    if field.required:
                        raise ToolWorkerError(
                            f"Context field '{field_name}' is required for ToolBox '{toolbox_def.name}'"
                        )
                    continue

            field_value: Any = self.binder.pull_context(ctx_field_bind)
            if field.attr_name:
                setattr(toolbox, field.attr_name, field_value)

        for field_name, res_field in toolbox_def.resource_fields.items():
            res_field_bind: ResourceBind | None = next(
                (
                    bind
                    for bind in job.resource_bindings
                    if bind.field_id == res_field.attr_name
                ),
                None,
            )
            if not res_field_bind:
                res_field_bind = next(
                    (
                        bind
                        for bind in setup.resource_bindings
                        if bind.field_id == res_field.attr_name
                    ),
                    None,
                )
                if not res_field_bind:
                    if res_field.required:
                        raise ToolWorkerError(
                            f"Context field '{field_name}' is required for ToolBox '{toolbox_def.name}'"
                        )
                    continue

            field_value = self.binder.load_resource(res_field_bind)
            if res_field.attr_name:
                setattr(toolbox, res_field.attr_name, field_value)

        params_doc = self.binder.find_document(
            document_id=params_bind.binded_id, context=params_bind.context
        )
        result_doc = self.binder.find_document(
            document_id=result_bind.binded_id, context=result_bind.context
        )

        params = None
        call_id = "no-id"
        chat_history: ChatHistory | None = None

        if params_doc.doc_model == "chat-history":
            chat_history = params_doc.load()
            assistant_message: AssistantMessage | None = None
            for msg in reversed(chat_history.messages):
                if isinstance(msg, AssistantMessage):
                    if not msg.tool_calls:
                        raise ToolWorkerError("Assistant's tool call is empty")
                    assistant_message = msg
                    break
                elif isinstance(msg, UserMessage):
                    break

            if not assistant_message:
                raise ToolWorkerError("Assistant's message not found")

            if assistant_message.tool_calls:
                for tool_call in assistant_message.tool_calls:
                    if tool_call.function.name == f"{setup.id}.{setup.active_tool}":
                        params = json.loads(tool_call.function.arguments)
                        call_id = tool_call.id
                        break
        else:
            params = params_doc.load()

        await job.update_status(JobStatus.WORKING, "Starting tool")
        result = await toolbox.run_tool(tool_name=setup.active_tool, params=params)

        await job.update_status(JobStatus.WORKING, "Saving results")
        if result_doc.doc_model == "chat-history":
            if chat_history is None or result_doc.doc_path != params_doc.doc_path:
                if result_doc.doc_path.exists():
                    chat_history = result_doc.load()
                else:
                    chat_history = ChatHistory()

            result_text: str
            if isinstance(result, str):
                result_text = result
            elif isinstance(result, dict):
                result_text = json.dumps(result, indent=2, ensure_ascii=False)
            elif isinstance(result, BaseModel):
                result_text = result.model_dump_json(indent=2, ensure_ascii=False)
            else:
                result_text = str(result)
            chat_history.messages.append(
                ToolMessage(
                    content=result_text,
                    tool_call_id=call_id,
                )
            )

            result_doc.save(chat_history)
        else:
            result_doc.save(result)

        await job.update_status(JobStatus.WORKING, "Saving bindings")
        for field_name, field in toolbox_def.context_fields.items():
            if not field.context_bind_type.is_output() or not field.attr_name:
                continue

            field_bind: ContextBind | None = next(
                (
                    bind
                    for bind in job.context_bindings
                    if bind.field_id == field.attr_name
                ),
                None,
            )
            if not field_bind:
                continue

            field_value = getattr(toolbox, field.attr_name)
            self.binder.push_context(field_bind, field_value)
