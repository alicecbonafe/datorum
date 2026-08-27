import asyncio
from collections.abc import AsyncGenerator
from enum import Enum

from ..binding.settings import (
    ContextBind,
    ResourceBind,
)
from .exceptions import JobStatusError


class Broadcaster:
    """Asynchronous subscription channel broadcaster for streaming events."""

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

    async def subscribe(self) -> AsyncGenerator[str]:
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
    """Job execution status enumeration."""

    IDLE = "idle"
    STARTING = "starting"
    WORKING = "working"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    FINISHED = "finished"
    CRASHED = "crashed"


class Job:
    """Execution state and binding parameters for an asynchronous job unit.

    A job is a runtime object defined by a set of bindings and an ID for a local
    context. Bindings must meet the Worker's requirements, though some workers may allow
    optional bindings. The local context definition enables the creation of delegated
    jobs and, consequently, collaboration between workers. Once defined, the Job's state
    can be monitored via Broadcasters.

    Jobs also provide pause/resume control by managing state update concurrency:

    * When a pause is requested, the state is updated to `JobStatus.PAUSING`.
    * When the Worker attempts to update the state to `JobStatus.WORKING`, the state is
      first updated to `JobStatus.PAUSED`, and execution enters a waiting state.
    * When a resume is requested, the operation that changes the state to
      `JobStatus.WORKING` is released.

    This makes the process transparent to the Worker, avoiding forced interruptions that
    could lead to data loss. Note that this is not a checkpoint, as the state is not
    persisted. If the application is interrupted, paused Jobs are lost. Checkpoints are
    implemented only for pipelines.

    :param id: Job unique identifier.
    :type id: str
    :param context_bindings: Configured context bindings.
    :type context_bindings: list[ContextBind], optional
    :param resource_bindings: Configured resource bindings.
    :type resource_bindings: list[ResourceBind], optional
    :param local_context_id: Identifier for the local context to be used.
    :type local_context_id: str, optional
    """

    def __init__(
        self,
        id: str,
        context_bindings: list[ContextBind] | None = None,
        resource_bindings: list[ResourceBind] | None = None,
        local_context_id: str | None = None,
    ):
        self.id: str = id
        self.context_bindings: list[ContextBind] = context_bindings or []
        self.resource_bindings: list[ResourceBind] = resource_bindings or []
        self.local_context_id: str = local_context_id or id

        self.status: JobStatus = JobStatus.IDLE
        self.message: str = "Job created"
        self.is_streaming: bool = False

        self.delegates: list[Job] = []

        self.update_broadcaster: Broadcaster = Broadcaster()
        self.chunk_broadcaster: Broadcaster = Broadcaster()
        self.log_broadcaster: Broadcaster = Broadcaster()

        self._pause_event = asyncio.Event()
        self._pause_event.set()

    async def update_status(self, status: JobStatus, message: str | None = None):
        if self.delegates and self.delegates[-1].status not in (
            JobStatus.IDLE,
            JobStatus.FINISHED,
            JobStatus.CRASHED,
        ):
            if status == JobStatus.CRASHED:
                await self.delegates[-1].update_status(status=status, message=message)
            else:
                raise JobStatusError(
                    f"Cannot update status - job's  last delegate seams to be active (job:'{self.id}', last_delegate:'{self.delegates[-1].id}')"
                )

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
        elif status == JobStatus.RESUMING:
            self._pause_event.set()

    async def push_chunk(self, chunk: str):
        self.chunk_broadcaster.push(chunk)

    async def push_log(self, log: str):
        self.log_broadcaster.push(log)

    async def finish_broadcasting(self):
        self.update_broadcaster.finish()
        self.chunk_broadcaster.finish()
        self.log_broadcaster.finish()

    def pause(self):
        if self.delegates and self.delegates[-1].status == JobStatus.WORKING:
            self.delegates[-1].pause()
        elif self.status in (JobStatus.PAUSING, JobStatus.PAUSED):
            pass
        elif self.status != JobStatus.WORKING:
            raise JobStatusError(f"Cannot pause job '{self.id}' ('{self.status}')")
        else:
            asyncio.create_task(
                self.update_status(
                    status=JobStatus.PAUSING,
                    message="Pausing worker...",
                )
            )

    def resume(self):
        if self.delegates and self.delegates[-1].status == JobStatus.PAUSED:
            self.delegates[-1].resume()
        elif self.status in (JobStatus.RESUMING, JobStatus.WORKING):
            pass
        elif self.status != JobStatus.PAUSED:
            raise JobStatusError(f"Cannot resume job '{self.id}' ('{self.status}')")
        else:
            asyncio.create_task(
                self.update_status(
                    status=JobStatus.RESUMING,
                    message="Resuming worker...",
                )
            )
