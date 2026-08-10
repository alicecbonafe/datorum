import json
from typing import Any

import httpx

from ..context import DocumentReference, MarkdownDocument
from ..exceptions import AgentWorkerException, InferenceException
from ..inference import (
    AIServiceProvider,
    AgentRole,
    ChatHistory,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ToolMessage
)
from ..tooling import ToolBoxSetUp, get_toolbox_definition
from .base import JobStatus, Job, Worker, TMP_CONTEXT
from .tools import ToolWorker


class AgentWorker(Worker):
    required_context: list[str] = ["user_prompt", "output"]

    _KNOWN_DELTA_KEYS = {"content", "tool_calls", "role"}

    def __init__(self,
        provider: AIServiceProvider,
        role: AgentRole,
        api_key: str,
        toolkit: list[ToolBoxSetUp] | None = None,
    ):
        super().__init__()
        self.provider: AIServiceProvider = provider
        self.role: AgentRole = role
        self.api_key: str = api_key
        self.toolkit: list[ToolBoxSetUp] = toolkit or []

    def _select_model(self) -> str:
        for candidate in self.role.preferred_models:
            if not self.provider.models or candidate in self.provider.models:
                return candidate
        if self.provider.default_model is not None:
            return self.provider.default_model
        raise AgentWorkerException(
            f"Can not determine model name for role '{self.role.id}' on provider '{self.provider.id}'"
        )

    def _toolbox_schema(self, toolbox: ToolBoxSetUp) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tool_name in toolbox.tools_enabled:
            toolbox_def = get_toolbox_definition(toolbox.toolbox_name)
            tool_def = toolbox_def.tools[tool_name]
            tool_data = tool_def.model_dump(mode="json", exclude={"name"})
            function_name = tool_data["function"]["name"]
            tool_data["function"]["name"] = f"{toolbox.id}.{function_name}"
            result.append(tool_data)
        return result

    def _toolkit_schema(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for toolbox in self.toolkit:
            result.extend(self._toolbox_schema(toolbox=toolbox))
        return result

    async def _call_streamer(self, request_payload: dict[str, Any], job: Job) -> tuple[dict[str, Any], dict[str, Any]]:
        request_payload = {**request_payload, "stream": True}
        content_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, Any]] = {}
        extra_parts: dict[str, Any] = {}
        response_meta: dict[str, Any] = {}
        finish_reason: str | None = None

        job.is_streaming = True
        try:
            async with httpx.AsyncClient(base_url=self.provider.base_url, timeout=120.0) as client:
                async with client.stream(
                    "POST", "chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request_payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        event = json.loads(data)

                        for key, value in event.items():
                            if key != "choices" and value is not None:
                                response_meta[key] = value

                        choice = event["choices"][0]
                        delta = choice.get("delta", {})
                        finish_reason = choice.get("finish_reason") or finish_reason
                        response_meta["finish_reason"] = finish_reason

                        if "content" in delta:
                            content_parts.append(delta["content"])
                            await job.push_chunk(delta["content"])

                        for tc_delta in delta.get("tool_calls", []) or []:
                            entry = tool_call_parts.setdefault(tc_delta["index"], {
                                "id": None, "type": "function",
                                "function": {"name": "", "arguments": ""},
                            })
                            if "id" in tc_delta:
                                entry["id"] = tc_delta["id"]
                            fn_delta = tc_delta.get("function") or {}
                            entry["function"]["name"] += fn_delta.get("name") or ""
                            entry["function"]["arguments"] += fn_delta.get("arguments") or ""

                        for key, value in delta.items():
                            if key in self._KNOWN_DELTA_KEYS:
                                continue
                            if isinstance(value, str):
                                extra_parts[key] = extra_parts.get(key, "") + value
                            else:
                                # extra parts that are not strings are not cumulative
                                # this will be handled when a concrete case appears
                                extra_parts[key] = value
        except httpx.HTTPError as e:
            raise InferenceException(f"Failed to call inference provider '{self.provider.id}': {e}") from e
        finally:
            job.is_streaming = False

        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts) or None,
            **extra_parts
        }
        if tool_call_parts:
            message["tool_calls"] = [tool_call_parts[i] for i in sorted(tool_call_parts)]

        return message, response_meta

    async def _call_fetcher(self, request_payload: dict[str, Any], job: Job) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            async with httpx.AsyncClient(base_url=self.provider.base_url, timeout=120.0) as client:
                response = await client.post(
                    "chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request_payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            raise InferenceException(
                f"Failed to call inference provider '{self.provider.id}': {e}"
            ) from e

        response_data = response.json()
        message = response_data["choices"][0]["message"]
        finish_reason = response_data["choices"][0]["finish_reason"]
        response_meta: dict[str, Any] = {"finish_reason": finish_reason}

        for key, value in response_data.items():
            if key != "choices" and value is not None:
                response_meta[key] = value

        return message, response_meta

    async def work(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Collecting agent resources")

        chat_history_doc: DocumentReference
        if "chat_history" in job.context.documents:
            chat_history_doc = job.context.documents["chat_history"]
        else:
            chat_history_doc = TMP_CONTEXT.create_document(
                id="chat-history",
                doc_model="chat-history",
                doc_type="application/json"
            )

        chat_history: ChatHistory
        if chat_history_doc.doc_path.exists():
            chat_history = chat_history_doc.load()
        else:
            chat_history = ChatHistory()

        system_instructions = self.role.system_instructions
        system_instructions_doc = job.context.documents["system_instructions"] \
            if "system_instructions" in job.context.documents else None
        if system_instructions_doc is not None:
            system_instructions = system_instructions_doc.load()
            if isinstance(system_instructions, MarkdownDocument):
                system_instructions = system_instructions.content

        if system_instructions:
            if len(chat_history.messages) == 0:
                chat_history.messages.append(SystemMessage(content=system_instructions))
            else:
                if chat_history.messages[0].role == "system":
                    chat_history.messages[0].content = system_instructions
                else:
                    chat_history.messages.insert(0, SystemMessage(content=system_instructions))

        user_prompt_doc = job.context.documents["user_prompt"]
        if user_prompt_doc is None:
            if len(chat_history.messages) == 0 or chat_history.messages[len(chat_history.messages)-1].role != "user":
                raise AgentWorkerException("User prompt not found")
        else:
            user_prompt = user_prompt_doc.load()
            if isinstance(user_prompt, MarkdownDocument):
                user_prompt = user_prompt.content
            chat_history.messages.append(UserMessage(content=user_prompt))

        model = self._select_model()
        toolkit_schema = self._toolkit_schema()

        while True:
            await job.update_status(JobStatus.WORKING, f"Calling model '{model}' at provider '{self.provider.id}'")
            request_payload: dict[str, Any] = {
                "model": model,
                "messages": chat_history.prepare_request(),
                "temperature": self.role.temperature,
                "top_p": self.role.top_p,
                "max_tokens": self.role.max_tokens,
            }

            if len(toolkit_schema) > 0:
                request_payload["tools"] = toolkit_schema

            if self.provider.supports_streaming:
                message, response_meta = await self._call_streamer(
                    request_payload=request_payload, job=job)
            else:
                message, response_meta = await self._call_fetcher(
                    request_payload=request_payload, job=job)

            assistant_message: AssistantMessage = AssistantMessage.model_validate(message)
            assistant_message.metadata = response_meta

            chat_history.messages.append(assistant_message)
            chat_history_doc.save(chat_history)

            if response_meta["finish_reason"] == "tool_calls":
                if not assistant_message.tool_calls:
                    raise AgentWorkerException(f"Agent's tool call is empty")
                for tool_call in assistant_message.tool_calls:
                    toolbox_setup_id, _, tool_name = tool_call.function.name.partition(".")
                    toolbox_setup: Optional[ToolBoxSetUp] = None
                    for _setup in self.toolkit:
                        if _setup.id == toolbox_setup_id:
                            toolbox_setup = _setup
                            break

                    if toolbox_setup is None:
                        tool_message = ToolMessage(
                            content=f"ToolBox '{toolbox_setup_id}' not found.",
                            tool_call_id=tool_call.id,
                        )
                        chat_history.messages.append(tool_message)
                        chat_history_doc.save(chat_history)
                        continue

                    toolbox_def = get_toolbox_definition(toolbox_setup.toolbox_name)
                    tool_def = toolbox_def.tools[tool_name]

                    tool_worker = ToolWorker(toolbox=toolbox_setup, tool_name=tool_name)
                    tool_job = tool_worker.create_delegated_job(origin=job, include_docs={
                        "tool_params": chat_history_doc,
                        "tool_result": chat_history_doc,
                    })
                    await tool_worker.run(tool_job)
                    chat_history = chat_history_doc.load()

            else:
                if assistant_message.content:
                    job.context.documents["output"].doc_path.write_text(assistant_message.content)
                break

