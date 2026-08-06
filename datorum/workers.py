from abc import ABC, abstractmethod
import asyncio
from enum import Enum
from pathlib import Path
from typing import Optional, AsyncGenerator
import uuid

import httpx

from .context import DocumentContext, DocumentReference, MarkdownDocument
from .exceptions import (
    AgentWorkerException,
    PauseRequested,
    InvalidJobTypeException,
    MissingContextException,
    InferenceException,
)
from .inference import (
    AIConfig,
    AIServiceProvider,
    AgentRole,
    ChatHistory,
    SystemMessage,
    UserMessage,
    AssistantMessage,
)
from .pipeline import PipelineCollection, PipeFlow
from .security import SecurityBackend
from .tooling import ToolBoxSetUp, ToolBoxDefinition, ToolBoxRegistry



class JobStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    WORKING = "working"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESTARTING = "restarting"
    FINISHED = "finished"
    CRASHED = "crashed"


class Job:

    def __init__(self, id: str, context: dict[str, DocumentReference]):
        self.id = id
        self.context = context

        self.status: JobStatus = JobStatus.IDLE
        self.message: str = "Job created"
        self.is_streaming: bool = False

        self.chunk_buffer: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self.log_buffer: asyncio.Queue[Optional[str]] = asyncio.Queue()

        self._pause_event = asyncio.Event()
        self._pause_event.set()

    async def update_status(self, status: JobStatus, message: str):
        if status == JobStatus.WORKING and self.status == JobStatus.PAUSING:
            self.status = JobStatus.PAUSED
            await self._pause_event.wait()

        self.status = status
        self.message = message

        if status == JobStatus.PAUSING:
            self._pause_event.clear()
        elif status == JobStatus.RESTARTING:
            self._pause_event.set()

    async def push_chunk(self, chunk: str):
        await self.chunk_buffer.put(chunk)

    async def push_log(self, log: str):
        await self.log_buffer.put(log)

    async def read_chunks(self) -> AsyncGenerator[str, None]:
        while True:
            chunk = await self.chunk_buffer.get()
            if chunk is None:
                break
            yield chunk

    async def read_logs(self) -> AsyncGenerator[str, None]:
        while True:
            log = await self.log_buffer.get()
            if log is None:
                break
            yield log

    async def finish_streams(self):
        await self.chunk_buffer.put(None)
        await self.log_buffer.put(None)


class WorkFlow(Job):

    def __init__(self, id: str, pipeflow: PipeFlow, context_collection: dict[str, DocumentContext]):
        super().__init__(id=id, context={})
        self.pipeflow = pipeflow
        self.context_collection = context_collection

    async def resolve_document(self, document_id: str, context_id: str | None = None) -> DocumentReference:
        if context_id is None:
            for context in self.context_collection.values():
                doc = context.get_document(document_id)
                if doc is not None:
                    return doc
            raise MissingContextException(f"Document '{document_id}' not found in workflow '{self.id}'")
        else:
            if context_id not in self.context_collection:
                raise MissingContextException(f"Context '{context_id}' not found in workflow '{self.id}'")
            doc = self.context_collection[context_id].get_document(document_id)
            if doc is None:
                raise MissingContextException(f"Document '{document_id}' not found in context '{context_id}'")
            return doc

    async def save_pipeflow(self):
        self.pipeflow.save()


class Worker(ABC):
    required_context: list[str] = []

    def __init__(self, worker_id: str):
        self.id: str = worker_id
        self.jobs: dict[str, Job] = {}

    def create_job(self, context: dict[str, DocumentReference]) -> str:
        for req in self.required_context:
            if req not in context:
                raise MissingContextException(f"Missing required context document for '{req}'")

        job_id = f"{self.__class__.__name__}-{uuid.uuid4().hex}"
        self.jobs[job_id] = Job(id=job_id, context=context)
        return job_id

    def start_job(self, job_id: str):
        if job_id not in self.jobs:
            raise InvalidJobTypeException(f"Job '{job_id}' not found")
        self.jobs[job_id].update_status(JobStatus.STARTING, "Starting worker...")
        asyncio.create_task(self._call_run(self.jobs[job_id]))

    def request_pause(self, job_id: str):
        if job_id in self.jobs:
            job = self.jobs[job_id]
            if job.status == JobStatus.WORKING:
                asyncio.create_task(job.update_status(JobStatus.PAUSING, "Pause requested"))

    def get_logger(self,):...  # TODO

    @abstractmethod
    async def run(self, job: Job):...

    async def _call_run(self, job: Job):
        try:
            self.run(job)
        except Exception as e:
            job.update_status(JobStatus.CRASHED, str(e))
        finally:
            job.finish_streams()


class ToolWorker(Worker):
    required_context: list[str] = ["settings", "tool_params", "tool_result"]

    def __init__(self, worker_id: str, toolbox: ToolBoxSetUp, tool_name: str):
        super().__init__(worker_id)
        self.toolbox = toolbox
        self.tool_name = tool_name

    async def run(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Collecting toolbox resources")

        toolbox_def = ToolBoxRegistry[self.toolbox.toolbox_id]
        toolbox = toolbox_def.create_toolbox(settings=job.context["settings"])

        if self.toolbox.logger_port.attribute_name is not None:
            setattr(toolbox, self.toolbox.logger_port.attribute_name, self.get_logger())
        if self.toolbox.monitor_port.attribute_name is not None:
            setattr(toolbox, self.toolbox.monitor_port.attribute_name, job)
        for name, port in self.toolbox.custom_ports.items():
            if name in job.context:
                setattr(toolbox, port.attribute_name, job.context[name])

        await job.update_status(JobStatus.WORKING, "Starting tool")

        output = toolbox.run_tool(
            tool_name = self.tool_name,
            params = job.context["tool_params"]
        )
        await job.update_status(JobStatus.WORKING, "Saving results")
        job.context["tool_result"].save(output)


class AgentWorker(Worker):
    required_context: list[str] = ["user_prompt", "output"]

    _KNOWN_DELTA_KEYS = {"content", "tool_calls", "role"}

    def __init__(self,
        worker_id: str,
        provider: AIServiceProvider,
        role: AgentRole,
        api_key: str,
        toolkit: list[ToolBoxSetUp] = []
    ):
        super().__init__(worker_id=worker_id)
        self.provider = provider
        self.role = role
        self.api_key = api_key
        self.toolkit = toolkit

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
            toolbox_def = ToolBoxRegistry[toolbox.toolbox_id]
            tool_def = toolbox_def.tools[tool_name]
            result.append(tool_def.model_dump(
                mode="json", exclude={"name"}))
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
                            entry["function"]["arguments"] += fn_delta.get("arguments")

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
                    "chat/completations",
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
        response_meta: dict[str, Any] = {}

        for key, value in response_data.items():
            if key != "choices" and value is not None:
                response_meta[key] = value

        return message, response_meta





    async def run(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Collecting agent resources")

        chat_history_doc = job.context["chat_history"] if "chat_history" in job.context else None
        chat_history: ChatHistory
        if chat_history_doc is None:
            chat_history = ChatHistory()
        else:
            chat_history = chat_history_doc.load()

        system_instructions_doc = job.context["system_instructions"] if "system_instructions" in job.context else None
        if system_instructions_doc is not None:
            system_instructions = system_instructions_doc.load()
            if isinstance(system_instructions, MarkdownDocument):
                system_instructions = system_instructions.content

            if len(chat_history.messages) == 0:
                chat_history.messages.append(SystemMessage(content=system_instructions))
            else:
                if chat_history.messages[0].role == "system":
                    chat_history.messages[0].content = system_instructions
                else:
                    chat_history.messages.insert(0, SystemMessage(content=system_instructions))

        user_prompt_doc = job.context["user_prompt"]
        if user_prompt_doc is None:
            if len(chat_history.messages) == 0 or chat_history.messages[len(chat_history.messages)-1].role != "user":
                raise AgentWorkerException("User prompt not found")
        else:
            user_prompt = user_prompt_doc.load();
            if isinstance(user_prompt, MarkdownDocument):
                user_prompt = user_prompt.content
            chat_history.messages.append(UserMessage(content=user_prompt))

        model = self._select_model()
        toolkit_schema = self._toolkit_schema()

        while True:
            await job.update_status(JobStatus.WORKING, f"Calling model '{model}' at provider '{self.provider.id}'")
            request_payload: dict[str, Any] = {
                "model": model,
                "messages": chat_history.model_dump(mode="json", exclude_none=True)["messages"],
                "temperature": self.role.temperature,
                "top_p": self.role.top_p,
                "max_tokens": self.role.max_tokens,
            }

            if len(toolkit_schema) > 0:
                request_payload["tools"] = toolkit_schema

            if self.provider.supports_streaming:
                message, response_meta = self._call_streamer(request_payload=request_payload, job=job)
            else:
                message, response_meta = self._call_fetcher(request_payload=request_payload, job=job)

            assistant_message: AssistantMessage = AssistantMessage.model_validate(message)
            assistant_message.metadata = response_meta

            chat_history.messages.append(assistant_message)
            chat_history_doc.save(chat_history)

            if finish_reason == "tool_calls":
                for tool_call in assistant_message.tool_calls:...
            else:
                break



class PipelineWorker(Worker):
    providers: dict[str, AIServiceProvider]
    roles: dict[str, AgentRole]

    tool_worker: Optional[ToolWorker]
    agent_worker: Optional[AgentWorker]

    def create_job(self, context: dict[str, DocumentReference]) -> str:
        raise TypeError
    def create_workflow(self, context_collection: dict[str, DocumentContext]) -> str:...
    def run(self, job: Job):
        assert isinstance(job, WorkFlow)



class DatorumProfile():
    username: str
    ai_config: Optional[AIConfig] = None
    context_collection: dict[str, DocumentContext]

    workers: dict[str, Worker] = {}


class DatorumOrquestrator():

    def __init__(self,
        security_backend: SecurityBackend,
        pipelines: PipelineCollection | Path,
        ai_config: Optional[AIConfig | Path] = None,
    ):
        self.security_backend = security_backend
        self.pipelines = pipelines if isinstance(pipelines, PipelineCollection) else PipelineCollection.load(pipelines)
        self.ai_config = ai_config if isinstance(ai_config, (AIConfig, None)) else AIConfig.load(pipelines)

        self.context_collection: dict[str, DocumentContext] = {}
        self.toolbox_collection: dict[str, ToolBoxSetUp] = {}

        self.profiles: dict[str, DatorumProfile] = {}
        self.sessions: dict[str, str] = {}

    def create_profile(self,
        username: str,
        ai_config: Optional[AIConfig | Path] = None,
        context_collection: dict[str, DocumentContext] = {}) -> DatorumProfile:...

    def get_profile(self, *, username: str | None = None, token: str | None = None) -> Optional[DatorumProfile]:...

    def register_session(self, username: str, token: str):
        if token not in self.sessions:
            for key, val in self.sessions:
                if val == username:
                    del self.sessions[key]
            self.sessions[token] = username

    def drop_session(self, token: str):
        if token in self.sessions:
            del self.sessions[token]

    def load_context(self, token: str, context_file_path: Path) -> str:...

    def load_global_context(self, context_file_path: Path) -> str:...

    def load_toolbox(self, toolbox_file_path: Path) -> str:...

    def prepare_tool_worker(self,
        token: str,
        toolbox_setup_id: str,
        tool_name: str,
    ) -> str:...

    def prepare_agent_worker(self,
        token: str,
        provider_id: str,
        role_id: str,
    ) -> str:...

    def prepare_pipeline_worker(self,
        token: str,
        pipeline_id: str,
    ) -> str:...

    def prepare_job(self,
        token: str,
        worker_id: str,
        documents: list[tuple[str | None, str]],
    ) -> str:...

    def prepare_worflow(self,
        token: str,
        worker_id: str,
        contexts: list[str],
    ) -> str:...

    def start_job(self,
        token: str,
        job_id: str,
    ):...

    def request_job_pause(self,
        token: str,
        job_id: str,
    ):...

    def get_job_status(self,
        token: str,
        job_id: str,
    ) -> dict:...

    async def stream_chunks(self,
        token: str,
        job_id: str,
    ) -> AsyncGenerator[str, None]:...

    async def stream_logs(self,
        token: str,
        job_id: str,
    ) -> AsyncGenerator[str, None]:...



