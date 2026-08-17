import asyncio
import pytest

from datorum.binding.binder import Binder
from datorum.context.settings import ContextBind, ResourceBind
from datorum.work.exceptions import WorkerStartUpError
from datorum.work.job import Job, JobStatus
from datorum.work.worker import Worker, _current_job


# ==============================================================================
# Mock Worker Implementations
# ==============================================================================

class DummyWorker(Worker):
    """Concrete Worker that completes successfully and checks ContextVar."""
    async def work(self, job: Job):
        # Verify ContextVar is set during execution
        assert _current_job.get() is job
        await job.push_chunk("processing...")


class FailingWorker(Worker):
    """Concrete Worker that raises an unhandled exception."""
    async def work(self, job: Job):
        raise ValueError("Worker process crashed unexpectedly!")


class BoundWorker(Worker):
    """Worker with strict binding requirements."""
    required_context_binds = ["req_ctx_1", "req_ctx_2"]
    required_resource_binds = ["req_res_1"]

    async def work(self, job: Job):
        pass


# ==============================================================================
# Worker Lifecycle Tests (`run`)
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.depends(on=["tests/test_work_job.py"])
async def test_worker_run_success():
    worker = DummyWorker(binder=Binder())
    job = Job(id="job_run_success")

    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert job.message == "Worker has finished the job."
    assert job.update_broadcaster.finished
    assert job.chunk_broadcaster.finished
    assert job.log_broadcaster.finished
    # Ensure ContextVar is reset after completion
    assert _current_job.get() is None


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_worker_run_success"])
async def test_worker_run_failure():
    worker = FailingWorker(binder=Binder())
    job = Job(id="job_run_failure")

    with pytest.raises(ValueError, match="Worker process crashed unexpectedly!"):
        await worker.run(job)

    assert job.status == JobStatus.CRASHED
    assert job.message == "Worker process crashed unexpectedly!"
    assert job.update_broadcaster.finished
    assert job.chunk_broadcaster.finished
    assert job.log_broadcaster.finished
    # Ensure ContextVar is reset even after failure
    assert _current_job.get() is None


# ==============================================================================
# Async Startup Tests (`start` & `_launch`)
# ==============================================================================

@pytest.mark.depends(on=["test_worker_run_failure"])
def test_worker_start_non_idle_raises_error():
    worker = DummyWorker(binder=Binder())
    job = Job(id="job_not_idle")
    job.status = JobStatus.WORKING

    with pytest.raises(WorkerStartUpError, match="Job 'job_not_idle' is not idle"):
        worker.start(job)


@pytest.mark.depends(on=["test_worker_run_failure"])
def test_worker_start_missing_bindings_raises_error():
    worker = BoundWorker(binder=Binder())
    job = Job(id="job_missing_binds")

    with pytest.raises(WorkerStartUpError, match="Missing bindings for job 'job_missing_binds'"):
        worker.start(job)


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_worker_run_success"])
async def test_worker_start_and_launch_success():
    worker = BoundWorker(binder=Binder())
    job = Job(
        id="job_valid_binds",
        context_bindings=[
            ContextBind(binded_id="req_ctx_1", field_id="req_ctx_1"),
            ContextBind(binded_id="req_ctx_2", field_id="req_ctx_2"),
        ],
        resource_bindings=[
            ResourceBind(factory_name="req_res_1", field_id="req_res_1"),
        ],
    )

    worker.start(job)
    # Give the background tasks time to process
    await asyncio.sleep(0.05)

    assert job.status == JobStatus.FINISHED
    assert job.message == "Worker has finished the job."


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_worker_run_failure"])
async def test_worker_launch_suppresses_background_exception():
    worker = FailingWorker(binder=Binder())
    job = Job(id="job_background_crash")

    # start() schedules _launch as an asyncio task
    worker.start(job)
    await asyncio.sleep(0.05)

    # Job status should be updated to CRASHED without unhandled task exceptions
    assert job.status == JobStatus.CRASHED
    assert job.message == "Worker process crashed unexpectedly!"