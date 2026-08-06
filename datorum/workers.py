from abc import ABC, abstractmethod
import asyncio
from enum import Enum
from pathlib import Path
from typing import Optional, AsyncGenerator
import uuid

from .context import DocumentContext, DocumentReference
from .exceptions import (
    PauseRequested,
    InvalidJobTypeException,
    MissingContextException,
)
from .inference import AIConfig, AIServiceProvider, AgentRole
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
    def run(self, job: Job):...

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

    def run(self, job: Job):
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

        await job.check()
        await job.update_status(JobStatus.WORKING, "Starting tool")

        output = toolbox.run_tool(
            tool_name = self.tool_name,
            params = job.context["tool_params"]
        )
        await job.check()
        await job.update_status(JobStatus.WORKING, "Saving results")
        job.context["tool_result"].save(output)


class AgentWorker(Worker):
    required_context: list[str] = ["system_instructions", "user_prompt", "output"]
    provider: AIServiceProvider
    role: AgentRole

    tool_worker: Optional[ToolJob]

    def run(self, job: Job):...


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



