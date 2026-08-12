from abc import ABC, abstractmethod
import asyncio
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, AsyncGenerator, Callable, Union
import uuid

from ..binding import ResourceBind, ContextBind, ContentType, get_resource_factory, validate_factory_signature
from ..context import DocumentContext, DocumentReference
from ..exceptions import InvalidJobTypeException, MissingContextException, InvalidContextBindException, InvalidResourceBindException


tmp_dir = f"/tmp/datorum_{datetime.now().strftime("%Y%m%d_%H%M%S")}"
TMP_CONTEXT = DocumentContext(id="tmp-context")
TMP_CONTEXT.base_path = Path(tmp_dir)
TMP_CONTEXT.base_path.mkdir(parents=True, exist_ok=True)

_current_job: ContextVar[Job | None] = ContextVar(
    "_current_job",
    default=None,
)


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


INPUT_CONTENT_TYPES = [
    "model",  "model-input",
    "text",   "text-input",
    "bytes",  "bytes-input",
    "document-path",  "document-metadata",
    "domain-path",    "domain-metadata",
]

OUTPUT_CONTENT_TYPES = [
    "model",  "model-output",
    "text",   "text-output",
    "bytes",  "bytes-output",
    "document-metadata",
    "domain-metadata",
]

DOCUMENT_CONTENT_TYPES = [
    "model",  "model-input",  "model-output",
    "text",   "text-input",   "text-output",
    "bytes",  "bytes-input",  "bytes-output",
    "document-path",  "document-metadata",
]

class Job:

    def __init__(
        self,
        id: str,
        context: dict[str, DocumentContext],
        context_bindings: Optional[dict[str, ContextBind]] = None,
        resource_bindings: Optional[dict[str, ResourceBind]] = None,
    ):
        self.id: str = id
        self.contexts: dict[str, DocumentContext] = contexts
        self.context_bindings: dict[str, ContextBind] = context_bindings or {}
        self.resource_bindings: dict[str, ResourceBind] = resource_bindings or {}
        self.result: Optional[str] = None

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

    def pause(self):
        self._propagate_status(
            previous_status=JobStatus.WORKING,
            next_status=JobStatus.PAUSING,
            next_message="Pausing worker...",
        )

    def restart(self):
        self._propagate_status(
            previous_status=JobStatus.PAUSED,
            next_status=JobStatus.RESTARTING,
            next_message="Restarting worker...",
        )

    def find_context_document(self, document_id: str) -> Optional[DocumentReference]:
        for ctx in self.contexts.values():
            doc = ctx.get_document(document_id)
            if doc:
                return doc
        return None

    def find_domain_context(self, domain: str) -> Optional[DocumentContext]:
        for ctx in self.contexts.values():
            if ctx.knows_domain(domain):
                return ctx
        return None

    def update_context_value(
        self,
        bind_id: str,
        bind_value: Any,
        content_type: str = "model",
        required: bool = False,
    ) -> bool:
        if content_type not in OUTPUT_CONTENT_TYPES:
            if required:
                raise InvalidContextBindException(
                    f"Content type '{content_type}' is not writable (bind: '{bind_id}')"
                )
            return False

        if content_type in DOCUMENT_CONTENT_TYPES:
            document = self.find_context_document(bind_id)
            if not document:
                if required:
                    raise MissingContextException(
                        f"Document '{bind_id}' not found in job context"
                    )
                return False
            
            if content_type == "document-metadata":
                assert isinstance(bind_value, dict)
                document.metadata.clear()
                document.metadata.update(bind_value)
                document.persistent.save()

            elif content_type.startswith("text"):
                assert isinstance(bind_value, str)
                document.doc_path.write_text(bind_value, encoding="utf-8")

            elif content_type.startswith("bytes"):
                assert isinstance(bind_value, bytes)
                document.doc_path.write_bytes(bind_value)

            else:
                document.save(bind_value)

            return True

        elif content_type == "domain-metadata":
            assert isinstance(bind_value, dict[str, Any])
            context = self.find_domain_context(bind_id)
            if not context:
                if required:
                    raise MissingContextException(
                        f"Domain '{bind_id}' is unkown in job context"
                    )
                return False
            context.set_domain_metadata(bind_id, bind_value)
            return True

        if required:
            raise InvalidContextBindException(
                f"Content type '{content_type}' is unknown (bind: '{bind_id}')"
            )
        return False

    def find_context_value(
        self,
        bind_id: str,
        content_type: str = "model",
        required: bool = False,
    ) -> Any:
        if content_type not in INPUT_CONTENT_TYPES:
            if required:
                raise InvalidContextBindException(
                    f"Content type '{content_type}' is not readable (bind: '{bind_id}')"
                )
            return None

        if content_type in DOCUMENT_CONTENT_TYPES:
            document = self.find_context_document(bind_id)
            if not document:
                if required:
                    raise MissingContextException(
                        f"Document '{bind_id}' not found in job context"
                    )
                return None
            
            if content_type == "document-metadata":
                return document.metadata

            doc_path = document.doc_path

            if content_type == "document-path":
                return doc_path

            if not doc_path.exists():
                if required:
                    raise MissingContextException(
                        f"File not found for document '{bind_id}' (path: '{doc_path}')"
                    )
                return None

            if content_type.startswith("text"):
                return doc_path.read_text(encoding="utf-8")
            if content_type.startswith("bytes"):
                return doc_path.read_bytes()

            return document.load()

        else:
            context = self.find_domain_context(bind_id)
            if not context:
                if required:
                    raise MissingContextException(
                        f"Domain '{bind_id}' is known in job context"
                    )
                return None

            if content_type == "domain-path":
                return context.get_domain_path(bind_id)
            if content_type == "domain-metadata":
                return context.get_domain_metadata(bind_id)

        if required:
            raise InvalidContextBindException(
                f"Content type '{content_type}' is unknown (bind: '{bind_id}')"
            )
        return None

    def _propagate_status(
        self,
        previous_status: JobStatus,
        next_status: JobStatus,
        next_message: Optiona[str] = None
    ):
        if self.status != previous_status:
            raise InvalidJobTypeException(
                f"Job '{self.id}' is not {str(previous_status.value).lower()}")

        last_delegate = self.delegates[-1] if self.delegates else None
        if last_delegate is not None and last_delegate.status == previous_status:
            last_delegate._propagate_status(
                previous_status=previous_status,
                next_status=next_status,
                next_message=next_message,
            )
        asyncio.create_task(self.update_status(next_status, next_message))


class Worker(ABC):
    required_documents: list[str] = []
    required_resources: list[str] = []

    def __init__(self, resource_factories: Optional[dict[str, Callable]] = None):
        self.factories: dict[str, Callable] = resource_factories or {}

    @abstractmethod
    async def work(self, job: Job):
        """Worker action, implemented by each subclass."""
        ...

    async def run(self):
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

    def start(self):
        if self.job.status != JobStatus.IDLE:
            raise InvalidJobTypeException(f"Job '{self.job.id}' is not idle")

        asyncio.create_task(self.job.update_status(JobStatus.STARTING, "Starting worker..."))
        asyncio.create_task(self._launch())

    async def _launch(self):
        """Entry point for a job started via a detached Task (start_job).
        run() already records the failure on job.status — this just keeps
        the exception from becoming an orphaned Task exception."""
        try:
            await self.run()
        except Exception as e:
            pass

    def resource_factory(self, name: str):
        def decorator(func):
            if not validate_factory_signature(func):
                raise InvalidResourceBindException(f"Invalid function signature for '{name}' resource factory")
            self.factories[name] = func
            return func
        return decorator

    def resolve_resource(self, name: str, selector: str | None) -> Any:
        factory = self.factories.get(name)
        if not factory:
            factory = get_resource_factory(name)
        return factory(selector)

    @classmethod
    def create_job(cls, context: JobContext) -> Job:
        for req in cls.required_documents:
            if req not in context.documents:
                raise MissingContextException(f"Missing required context document for '{req}'")

        job_id = f"{cls.__name__}-{uuid.uuid4().hex}"
        job = Job(id=job_id, context=context)
        return job

    @classmethod
    def create_delegated_job(
        cls, origin: Job,
        include_docs: Optional[dict[str, DocumentReference]] = None,
    ) -> Job:
        context = JobContext(
            documents={**origin.context.documents, **(include_docs or {})},
            domains={**origin.context.domains},
            resources={**origin.context.resources},
        )
        job = cls.create_job(context)
        origin.delegates.append(job)
        return job


