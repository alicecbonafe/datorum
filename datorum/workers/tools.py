import json
from typing import Any

from pydantic import BaseModel

from ..exceptions import ToolWorkerException, MissingContextException
from ..inference import ChatHistory, AssistantMessage, ToolMessage
from ..tooling import ToolBoxSetUp, get_toolbox_definition
from ..wiring import BaseBind
from .base import JobStatus, Job, Worker


class ToolWorker(Worker):
    required_context: list[str] = ["tool_params", "tool_result"]

    def __init__(self, toolbox: ToolBoxSetUp, tool_name: str):
        super().__init__()
        self.toolbox = toolbox
        self.tool_name = tool_name

    async def work(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Collecting toolbox resources")

        toolbox_def = get_toolbox_definition(self.toolbox.toolbox_name)
        if self.tool_name not in toolbox_def.tools:
            raise ToolWorkerException(f"Tool '{self.tool_name}' not found in ToolBox '{toolbox_def.name}'")
        # tool_def = toolbox_def.tools[self.tool_name]
        toolbox = toolbox_def.create_toolbox()

        for field_name, field in toolbox_def.fields.items():
            port = self.toolbox.custom_ports.get(field_name, None)
            field_value: Any | None = None
            if port:
                bind: BaseBind = port.bind
                field_value = bind.resolve(
                    documents=job.context.documents,
                    domains=job.context.domains,
                    resources=job.context.resources,
                )

            if field_value is not None:
                setattr(toolbox, field.attr_name, field_value)
            elif field.required:
                raise MissingContextException(f"Missing bind for '{self.toolbox.id}.{field_name}")

        tool_params_doc = job.context.documents["tool_params"]
        tool_result_doc = job.context.documents["tool_result"]

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

        await job.update_status(JobStatus.WORKING, "Starting tool")

        output = await toolbox.run_tool(
            tool_name = self.tool_name,
            params = tool_params
        )

        await job.update_status(JobStatus.WORKING, "Saving results")
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
