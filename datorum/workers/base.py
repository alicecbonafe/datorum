from abc import ABC, abstractmethod
import asyncio
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, AsyncGenerator, Callable
import uuid

from ..context import DocumentContext, DocumentReference
from ..exceptions import InvalidJobTypeException, MissingContextException


tmp_dir = f"/tmp/datorum_{datetime.now().strftime("%Y%m%d_%H%M%S")}"
TMP_CONTEXT = DocumentContext(id="tmp-context")
TMP_CONTEXT.base_path = Path(tmp_dir)
TMP_CONTEXT.base_path.mkdir(parents=True, exist_ok=True)


class Broadcaster:
    def __init__(self):
        self.history: list[str] = []
        self.subscribers: list[asyncio.Queue] = []
        self.finished = False

    def push(self, item: str):
        self.history.append(item)
        for q in self.subscribers:
            q.put_nowait(item)

    def finish(self):
        self.finished = True
        for q in self.subscribers:
            q.put_nowait(None)

    async def subscribe(self) -> AsyncGenerator[str, None]:
        q: asyncio.Queue = asyncio.Queue()
        for item in self.history:  # replay backlog
            q.put_nowait(item)
        if self.finished:
            q.put_nowait(None)
        self.subscribers.append(q)
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield item
        finally:
            self.subscribers.remove(q)  # cleanup on disconnect


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

        self.update_broadcaster: Broadcaster = Broadcaster()
        self.chunk_broadcaster: Broadcaster = Broadcaster()
        self.log_broadcaster: Broadcaster = Broadcaster()

        self._pause_event = asyncio.Event()
        self._pause_event.set()

    async def update_status(self, status: JobStatus, message: Optional[str] = None):
        if status == JobStatus.WORKING and self.status == JobStatus.PAUSING:
            self.status = JobStatus.PAUSED
            self.update_broadcaster.push(f"[{self.status.value.lower()}]")
            await self._pause_event.wait()

        self.status = status
        self.message = message or self.message
        update_message = f" {message}" if message else ""
        self.update_broadcaster.push(f"[{self.status.value.lower()}]{update_message}")

        if status == JobStatus.PAUSING:
            self._pause_event.clear()
        elif status == JobStatus.RESTARTING:
            self._pause_event.set()

    async def push_chunk(self, chunk: str):
        await self.chunk_broadcaster.push(chunk)

    async def push_log(self, log: str):
        await self.log_broadcaster.push(log)

    async def finish_broadcasting(self):
        await self.update_broadcaster.finish()
        await self.chunk_broadcaster.finish()
        await self.log_broadcaster.finish()


class Worker(ABC):
    required_context: list[str] = []

    def __init__(self):
        self.jobs: dict[str, Job] = {}

    @abstractmethod
    async def work(self, job: Job):
        """Worker action, implemented by each subclass."""
        ...

    async def run(self, job: Job):
        """Drives one job through its full lifecycle."""
        token = _current_job.set(job)
        try:
            await self.work(job)
            await job.update_status(JobStatus.FINISHED, "Worker has finished the job.")
        except Exception as e:
            await job.update_status(JobStatus.CRASHED, str(e))
            raise
        finally:
            _current_job.reset(token)
            await job.finish_broadcasting()

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

        asyncio.create_task(job.update_status(JobStatus.STARTING, "Starting worker..."))
        asyncio.create_task(self._launch(self.jobs[job_id]))

    def restart_job(self, job_id: str):
        if job_id not in self.jobs:
            raise InvalidJobTypeException(f"Job '{job_id}' not found")
        self._propagate_status(
            job=self.jobs[job_id],
            previous_status=JobStatus.PAUSED,
            next_status=JobStatus.RESTARTING,
            next_message="Restarting worker...",
        )

    def request_pause(self, job_id: str):
        if job_id not in self.jobs:
            raise InvalidJobTypeException(f"Job '{job_id}' not found")
        self._propagate_status(
            job=self.jobs[job_id],
            previous_status=JobStatus.WORKING,
            next_status=JobStatus.PAUSING,
            next_message="Restarting worker...",
        )

    async def _launch(self, job: Job):
        """Entry point for a job started via a detached Task (start_job).
        run() already records the failure on job.status — this just keeps
        the exception from becoming an orphaned Task exception."""
        try:
            await self.run(job)
            # await job.update_status(JobStatus.FINISHED, "Worker has finished the job.")
        except Exception as e:
            pass
            # await job.update_status(JobStatus.CRASHED, str(e))
        # finally:
        #     await job.finish_broadcasting()

    def _propagate_status(
        self,
        job: Job,
        previous_status: JobStatus,
        next_status: JobStatus,
        next_message: Optiona[str] = None
    ):
        if job.status != previous_status:
            raise InvalidJobTypeException(
                f"Job '{job.id}' is not {str(previous_status.value).lower()}")

        last_delegate = job.delegates[-1] if job.delegates else None
        if last_delegate is not None and last_delegate.status == previous_status:
            self._propagate_status(
                job=last_delegate,
                previous_status=previous_status,
                next_status=next_status,
                next_message=next_message,
            )
        asyncio.create_task(job.update_status(next_status, next_message))


