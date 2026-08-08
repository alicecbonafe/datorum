from abc import ABC, abstractmethod
import asyncio
from copy import deepcopy
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Optional, AsyncGenerator, Callable, Any
import uuid

import httpx
from pydantic import BaseModel

from .context import DocumentContext, DocumentReference, MarkdownDocument
from .exceptions import (
    AgentWorkerException,
    PauseRequested,
    InvalidJobTypeException,
    MissingContextException,
    InferenceException,
    ToolWorkerException,
    PipelineWorkerException,
)
from .inference import (
    AIConfig,
    AIServiceProvider,
    AgentRole,
    ChatHistory,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ToolMessage
)
from .pipeline import (
    PipelineCollection,
    PipeFlow,
    PipeFlowState,
    HumanInteractionStep,
    ToolStep,
    AgentStep,
    DecisionStep,
)
from .security import SecurityBackend
from .tooling import ToolBoxSetUp, ToolBoxDefinition, get_toolbox_definition
from .wiring import (
    BaseBind,
    DocumentBind, DocumentRawBind, DocumentPathBind,
    DomainPathBind, ResourceBind,
)


tmp_dir = f"/tmp/datorum_{datetime.now().strftime("%Y%m%d_%H%M%S")}"
TMP_CONTEXT = DocumentContext(id="tmp-context")
TMP_CONTEXT.base_path = Path(tmp_dir)
TMP_CONTEXT.base_path.mkdir(parents=True, exist_ok=True)


class JobStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    WORKING = "working"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESTARTING = "restarting"
    FINISHED = "finished"
    CRASHED = "crashed"


class JobContext:

    def __init__(self,
        documents: dict[str, DocumentReference] | None = None,
        domains: dict[str, Path] | None = None,
        resources: dict[str, Callable] | None = None,
    ):
        self.documents = documents or {}
        self.domains = domains or {}
        self.resources = resources or {}


class Job:

    def __init__(self, id: str, context: JobContext):
        self.id = id
        self.context = context

        self.status: JobStatus = JobStatus.IDLE
        self.message: str = "Job created"
        self.is_streaming: bool = False

        self.delegates: list[Job] = []

        self.chunk_buffer: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self.log_buffer: asyncio.Queue[Optional[str]] = asyncio.Queue()

        self._pause_event = asyncio.Event()
        self._pause_event.set()

    async def update_status(self, status: JobStatus, message: Optional[str] = None):
        if status == JobStatus.WORKING and self.status == JobStatus.PAUSING:
            self.status = JobStatus.PAUSED
            await self._pause_event.wait()

        self.status = status
        self.message = message or self.message

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

    async def create_delegate(self, new_id: str, ) -> "Job":
        new_context = JobContext(
            documents={
                **self.context.documents,
                **(include_docs or {})
            },
            domains={**self.context.domains},
            resources={**self.context.resources},
        )
        new_job = Job(id=new_id, )

class Worker(ABC):
    required_context: list[str] = []

    def __init__(self):
        self.jobs: dict[str, Job] = {}

    def create_job(self, context: JobContext) -> Job:
        for req in self.required_context:
            if req not in context.documents:
                raise MissingContextException(f"Missing required context document for '{req}'")

        job_id = f"{self.__class__.__name__}-{uuid.uuid4().hex}"
        job = Job(id=job_id, context=context)
        self.jobs[job_id] = job
        return job

    def create_delegated_job(
        self, origin: Job,
        include_docs: Optional[dict[str, DocumentReference]] = None,
    ) -> Job:
        context = JobContext(
            documents={**origin.context.documents, **(include_docs or {})},
            domains={**origin.context.domains},
            resources={**origin.context.resources},
        )
        job = self.create_job(context)
        origin.delegates.append(job)
        return job


    def start_job(self, job_id: str):
        if job_id not in self.jobs:
            raise InvalidJobTypeException(f"Job '{job_id}' not found")

        job = self.jobs[job_id]

        if job.status != JobStatus.IDLE:
            raise InvalidJobTypeException(f"Job '{job_id}' is not idle")

        await job.update_status(JobStatus.STARTING, "Starting worker...")
        asyncio.create_task(self._call_run(self.jobs[job_id]))

    def restart_job(self, job_id: str):
        if job_id not in self.jobs:
            raise InvalidJobTypeException(f"Job '{job_id}' not found")

        job = self.jobs[job_id]

        if job.status != JobStatus.PAUSED:
            raise InvalidJobTypeException(f"Job '{job_id}' is not paused")

        await job.update_status(JobStatus.RESTARTING, "Restarting worker...")

    def request_pause(self, job_id: str):
        if job_id not in self.jobs:
            raise InvalidJobTypeException(f"Job '{job_id}' not found")

        job = self.jobs[job_id]

        if job.status != JobStatus.WORKING:
            raise InvalidJobTypeException(f"Job '{job_id}' is inactive")

        last_delegate = job.delegates[len(job.delegates)-1] if len(job.delegates) > 0 else None
        if last_delegate is not None and last_delegate.status == JobStatus.WORKING:
            await last_delegate.update_status(JobStatus.PAUSING, "Pause requested")
        asyncio.create_task(job.update_status(JobStatus.PAUSING, "Pause requested"))

    def get_logger(self,):...  # TODO

    @abstractmethod
    async def run(self, job: Job):...

    async def _call_run(self, job: Job):
        try:
            await self.run(job)
            await job.update_status(JobStatus.FINISHED, "Worker has finished the job.")
        except Exception as e:
            await job.update_status(JobStatus.CRASHED, str(e))
        finally:
            await job.finish_streams()


class ToolWorker(Worker):
    required_context: list[str] = ["tool_params", "tool_result"]

    def __init__(self, toolbox: ToolBoxSetUp, tool_name: str):
        super().__init__()
        self.toolbox = toolbox
        self.tool_name = tool_name

    async def run(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Collecting toolbox resources")

        toolbox_def = get_toolbox_definition(self.toolbox.toolbox_name)
        if self.tool_name not in toolbox_def.tools:
            raise ToolWorkerException(f"Tool '{self.tool_name}' not found in ToolBox '{toolbox_def.name}'")
        tool_def = toolbox_def.tools[self.tool_name]
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
                assistant_message: AssistantMessage = chat_history.messages[len(chat_history.messages)-1]
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

        output = toolbox.run_tool(
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
        response_meta: dict[str, Any] = {}

        for key, value in response_data.items():
            if key != "choices" and value is not None:
                response_meta[key] = value

        return message, response_meta

    async def run(self, job: Job):
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
            system_instructions = system_instructions.content \
                if isinstance(system_instructions, MarkdownDocument) \
                    else system_instructions_doc.load()

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
                    job.current_delegate = tool_job
                    await tool_worker._call_run(tool_job)
                    chat_history = chat_history_doc.load()

            else:
                if assistant_message.content:
                    job.context.documents["output"].doc_path.write_text(assistant_message.content)
                break



class PipelineWorker(Worker):

    def __init__(
        self,
        pipeflow: PipeFlow,
        providers: dict[str, AIServiceProvider],
        provider_api_keys: dict[str, str],
        roles: dict[str, AgentRole],
        toolkit: list[ToolBoxSetUp],
    ):
        self.pipeflow = pipeflow
        self.providers = providers
        self.provider_api_keys = provider_api_keys
        self.roles = roles
        self.toolkit = toolkit

    async def save_flow(
        self, *,
        state: Optional[PipeFlowState] = None,
        step_id: Optional[str] = None
    ):
        self.pipeflow.state = state or self.pipeflow.state
        now = datetime.now().astimezone()
        if state != PipeFlowState.planning and self.pipeflow.started_at is None:
            self.pipeflow.started_at = now
        self.pipeflow.last_updated_at = now
        if state in [PipeFlowState.finished, PipeFlowState.crashed] and self.pipeflow.finished_at is None:
            self.pipeflow.finished_at = now
        self.pipeflow.save()

    async def run(self, job: Job):
        current_step_id: str | None = self.pipeflow.current_step_id

        if current_step_id is None and self.pipeflow.started_at is None:
            current_step_id = self.pipeflow.pipeline.first_step_id
            self.pipeflow.current_step_id = current_step_id
            self.save_flow(PipeFlowState.started)

        while current_step_id is not None:
            if current_step_id not in self.pipeflow.pipeline.steps:
                raise PipelineWorkerException(f"Step '{current_step_id}' not found in Pipeline '{self.pipeflow.pipeline.id}'")

            current_step = self.pipeflow.pipeline.steps[current_step_id]
            if current_step.type == "human":
                assert isinstance(current_step, HumanInteractionStep)
                job.update_status(JobStatus.PAUSING, "Waiting for human interaction.")
                job.update_status(JobStatus.WORKING, "Resuming pipeline...")
            elif current_step.type == "tool":
                assert isinstance(current_step, ToolStep)
                job.update_status(JobStatus.WORKING, f"Running tool step '{current_step_id}'...")

                tool_params_doc_id = current_step.tool_params_port.bind.document_id
                tool_result_doc_id = current_step.tool_result_port.bind.document_id
                if tool_params_doc_id not in job.context.documents:
                    raise PipelineWorkerException(f"Step '{current_step_id}' failed, document '{tool_params_doc_id}' not found in context")
                tool_params_doc = job.context.documents[tool_params_doc_id]
                tool_result_doc = job.context.documents[tool_result_doc_id]
                
                tool_job_context = JobContext(
                    documents={
                        **job.context.documents,
                        "tool_params": tool_params_doc,
                        "tool_result": tool_result_doc,
                    },
                    domains=job.context.domains,
                    resources=job.context.resources
                )

                tool_worker = ToolWorker(
                    toolbox=self.toolkit[current_step.toolbox_setup_id],
                    tool_name=current_step.tool_name,
                )
                job.current_delegate = tool_worker.create_job(
                    context=tool_job_context
                )

                job.update_status(JobStatus.WORKING, "Starting tool worker...")
                await tool_worker.run(job=job.current_delegate)
                job.update_status(JobStatus.WORKING, "Tool worker has completed the job.")
            elif current_step.type == "agent":
                assert isinstance(current_step, AgentStep)
                job.update_status(JobStatus.WORKING, f"Running agent step '{current_step_id}'...")

                # TODO
            elif current_step.type == "decision":
                assert isinstance(current_step, DecisionStep)
                # TODO

            self.pipeflow.step_history.append(current_step_id)
            current_step_id = current_step.target_id
            self.pipeflow.current_step_id = current_step_id
            self.save_flow()



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
        self.pipelines: PipelineCollection = pipelines \
            if isinstance(pipelines, PipelineCollection) \
                else PipelineCollection.load(pipelines)
        self.ai_config: Optional[AIConfig] = ai_config \
            if ai_config is None or isinstance(ai_config, AIConfig) \
                else AIConfig.load(ai_config)

        self.context_collection: dict[str, DocumentContext] = {}
        self.toolbox_collection: dict[str, ToolBoxSetUp] = {}

        self.profiles: dict[str, DatorumProfile] = {}
        self.sessions: dict[str, str] = {}

    def create_profile(self,
        username: str,
        ai_config: Optional[AIConfig | Path] = None,
        context_collection: dict[str, DocumentContext] | None = None) -> DatorumProfile:...

    def get_profile(self, *, username: str | None = None, token: str | None = None) -> Optional[DatorumProfile]:...

    def register_session(self, username: str, token: str):
        if token not in self.sessions.items():
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



