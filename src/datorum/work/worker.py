import asyncio
import logging
from abc import ABC, abstractmethod
from contextvars import ContextVar
from pathlib import Path
from typing import ClassVar

from ..binding.binder import Binder
from ..context.settings import DocumentContext
from .exceptions import WorkerStartUpError
from .job import Job, JobStatus

_current_job: ContextVar[Job | None] = ContextVar(
    "_current_job",
    default=None,
)


class Worker(ABC):
    required_context_binds: ClassVar[list[str]] = []
    required_resource_binds: ClassVar[list[str]] = []

    def __init__(self, binder: Binder):
        self.binder: Binder = binder
        self.jobs: dict[str, Job] = {}

        self.logger = logging.getLogger(self.__class__.__qualname__)

    @abstractmethod
    async def work(self, job: Job):
        """Worker action, implemented by each subclass."""
        ...

    async def run(self, job: Job):
        """Drives one job through its full lifecycle."""
        token = _current_job.set(job)
        if job.id not in self.jobs:
            self.jobs[job.id] = job
        try:
            await self.work(job)
            await job.update_status(JobStatus.FINISHED, "Worker has finished the job.")
        except Exception as e:
            await job.update_status(JobStatus.CRASHED, str(e))
            raise
        finally:
            _current_job.reset(token)
            await job.finish_broadcasting()

    def start(self, job: Job):
        if job.status != JobStatus.IDLE:
            raise WorkerStartUpError(f"Job '{job.id}' is not idle")

        missing_bindings: list[str] = []
        binds = {bind.field_id for bind in job.context_bindings}
        for req in self.required_context_binds:
            if req not in binds:
                missing_bindings.append(f"ctx:{req}")
        binds = {bind.factory_name for bind in job.resource_bindings}
        for req in self.required_resource_binds:
            if req not in binds:
                missing_bindings.append(f"res:{req}")
        if missing_bindings:
            raise WorkerStartUpError(
                f"Missing bindings for job '{job.id}': {missing_bindings}"
            )

        asyncio.create_task(job.update_status(JobStatus.STARTING, "Starting worker..."))
        asyncio.create_task(self._launch(job=job))

    async def _launch(self, job: Job):
        """Entry point for a job started via a detached Task (start_job).
        run() already records the failure on job.status — this just keeps
        the exception from becoming an orphaned Task exception."""
        try:
            await self.run(job=job)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(exc)
