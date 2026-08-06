from abc import ABC, abstractmethod
import asyncio
from enum import Enum
from pathlib import Path
from typing import Optional, AsyncGenerator
import uuid

from .context import DocumentContext, DocumentReference
from .exceptions import MissingContextException
from .inference import AIConfig, AIServiceProvider, AgentRole
from .pipeline import PipelineCollection, PipeFlow
from .security import SecurityBackend
from .tooling import ToolBoxSetUp, ToolBoxDefinition



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

    async def update_status(self, status: JobStatus, message: str):
        self.status = status
        self.message = message

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


class Worker(ABC):
    id: str
    required_context: list[str] = []
    jobs: dict[str, Job]

    def create_job(self, context: dict[str, DocumentReference]) -> str:...

    def start_job(self, job_id: str):
        asyncio.create_task(self.run(self.jobs[job_id]))

    def request_pause(self, job_id: str):...

    @abstractmethod
    async def run(self, job: Job):...


class ToolWorker(Worker):
    required_context: list[str] = ["tool_params", "tool_result"]
    toolbox: ToolBoxSetUp
    tool_name: str

    async def run(self, job: Job):...


class AgentWorker(Worker):
    required_context: list[str] = ["system_instructions", "user_prompt", "output"]
    provider: AIServiceProvider
    role: AgentRole

    tool_worker: Optional[ToolJob]

    async def run(self, job: Job):...


class PipelineWorker(Worker):
    providers: dict[str, AIServiceProvider]
    roles: dict[str, AgentRole]

    tool_worker: Optional[ToolWorker]
    agent_worker: Optional[AgentWorker]

    def create_job(self, context: dict[str, DocumentReference]) -> str:
        raise TypeError
    def create_workflow(self, context_collection: dict[str, DocumentContext]) -> str:...
    async def run(self, job: Job):
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



