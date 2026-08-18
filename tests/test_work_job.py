import asyncio
import pytest

from datorum.binding.settings import ContextBind, ResourceBind
from datorum.work.exceptions import JobStatusError
from datorum.work.job import Broadcaster, Job, JobStatus


# ==============================================================================
# Broadcaster Tests
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.depends(on=["tests/test_context_settings.py"])
async def test_broadcaster_history_and_subscribe():
    broadcaster = Broadcaster()
    broadcaster.push("item_1")
    broadcaster.push("item_2")
    broadcaster.finish()

    # Backlog replay check
    items = []
    async for item in broadcaster.subscribe():
        items.append(item)

    assert items == ["item_1", "item_2"]


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_broadcaster_history_and_subscribe"])
async def test_broadcaster_live_streaming():
    broadcaster = Broadcaster()
    received_items = []

    async def subscriber_coro():
        async for item in broadcaster.subscribe():
            received_items.append(item)

    task = asyncio.create_task(subscriber_coro())
    await asyncio.sleep(0.01)  # Give time for subscription to establish

    assert len(broadcaster.subscribers) == 1

    broadcaster.push("live_1")
    broadcaster.push("live_2")
    broadcaster.finish()

    await task
    assert received_items == ["live_1", "live_2"]
    # Verify cleanup on disconnect
    assert len(broadcaster.subscribers) == 0


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_broadcaster_history_and_subscribe"])
async def test_broadcaster_cleanup_on_cancel():
    broadcaster = Broadcaster()

    async def subscriber_coro():
        async for _ in broadcaster.subscribe():
            pass

    task = asyncio.create_task(subscriber_coro())
    await asyncio.sleep(0.01)
    assert len(broadcaster.subscribers) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Queue should be removed from subscribers in finally block
    assert len(broadcaster.subscribers) == 0


# ==============================================================================
# Job Tests
# ==============================================================================

@pytest.mark.depends(on=["tests/test_context_settings.py"])
def test_job_initialization():
    ctx_bind = ContextBind(binded_id="ctx_1", field_id="ctx_doc")
    res_bind = ResourceBind(factory_name="res_1", field_id="resource")

    job = Job(
        id="job_1",
        context_bindings=[ctx_bind],
        resource_bindings=[res_bind],
    )

    assert job.id == "job_1"
    assert job.context_bindings == [ctx_bind]
    assert job.resource_bindings == [res_bind]
    assert job.status == JobStatus.IDLE
    assert job.message == "Job created"
    assert job.is_streaming is False
    assert job.delegates == []


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_job_initialization"])
async def test_job_update_status():
    job = Job(id="job_status")

    await job.update_status(JobStatus.STARTING, message="Initializing worker")
    assert job.status == JobStatus.STARTING
    assert job.message == "Initializing worker"
    assert job.update_broadcaster.history[-1] == "[starting] Initializing worker"

    await job.update_status(JobStatus.FINISHED)
    assert job.status == JobStatus.FINISHED
    # Retains previous message when None is passed
    assert job.message == "Initializing worker"
    assert job.update_broadcaster.history[-1] == "[finished]"


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_job_initialization", "test_broadcaster_cleanup_on_cancel"])
async def test_job_push_chunks_logs_and_finish():
    job = Job(id="job_streams")

    await job.push_chunk("chunk_data_1")
    await job.push_log("log_message_1")

    assert job.chunk_broadcaster.history == ["chunk_data_1"]
    assert job.log_broadcaster.history == ["log_message_1"]

    await job.finish_broadcasting()
    assert job.update_broadcaster.finished
    assert job.chunk_broadcaster.finished
    assert job.log_broadcaster.finished


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_job_update_status", "test_broadcaster_cleanup_on_cancel"])
async def test_job_pause_and_resume_flow():
    job = Job(id="job_pause_flow")
    await job.update_status(JobStatus.WORKING, message="Processing...")

    # Pause triggers background update task
    job.pause()
    await asyncio.sleep(0.01)
    assert job.status == JobStatus.PAUSING

    # When update_status(WORKING) is called during PAUSING, it enters PAUSED and awaits resume
    worker_task = asyncio.create_task(job.update_status(JobStatus.WORKING))
    await asyncio.sleep(0.01)

    assert job.status == JobStatus.PAUSED
    assert "[paused]" in job.update_broadcaster.history

    # Resume job
    job.resume()
    await worker_task
    assert job.status == JobStatus.WORKING


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_job_update_status"])
async def test_job_pause_resume_edge_cases():
    job = Job(id="job_pause_errors")

    # Calling pause when IDLE raises JobStatusError
    with pytest.raises(JobStatusError, match="Cannot pause job 'job_pause_errors'"):
        job.pause()

    # Calling resume when IDLE raises JobStatusError
    with pytest.raises(JobStatusError, match="Cannot resume job 'job_pause_errors'"):
        job.resume()

    await job.update_status(JobStatus.WORKING)

    # Calling resume when already WORKING is a no-op
    job.resume()
    assert job.status == JobStatus.WORKING

    job.pause()
    await asyncio.sleep(0.01)
    assert job.status == JobStatus.PAUSING

    # Calling pause when PAUSING is a no-op
    job.pause()
    assert job.status == JobStatus.PAUSING


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_job_update_status"])
async def test_job_delegates_active_status_error():
    parent_job = Job(id="parent_job")
    delegate_job = Job(id="delegate_job")
    parent_job.delegates.append(delegate_job)

    await delegate_job.update_status(JobStatus.WORKING)

    # Updating parent while delegate is active should raise error
    with pytest.raises(JobStatusError, match="Cannot update status - job's  last delegate seams to be active"):
        await parent_job.update_status(JobStatus.FINISHED)


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_job_delegates_active_status_error"])
async def test_job_delegates_crash_propagation():
    parent_job = Job(id="parent_job")
    delegate_job = Job(id="delegate_job")
    parent_job.delegates.append(delegate_job)

    await delegate_job.update_status(JobStatus.WORKING)

    # Status update to CRASHED propagates to the delegate
    await parent_job.update_status(JobStatus.CRASHED, message="Fatal crash")
    assert delegate_job.status == JobStatus.CRASHED
    assert delegate_job.message == "Fatal crash"


@pytest.mark.asyncio
@pytest.mark.depends(on=["test_job_update_status"])
async def test_job_delegates_pause_resume():
    parent_job = Job(id="parent_job")
    delegate_job = Job(id="delegate_job")
    parent_job.delegates.append(delegate_job)

    await parent_job.update_status(JobStatus.WORKING)
    await delegate_job.update_status(JobStatus.WORKING)

    # Pause forwards to delegate
    parent_job.pause()
    await asyncio.sleep(0.01)
    assert delegate_job.status == JobStatus.PAUSING

    # Force delegate status to PAUSED for testing resume delegation
    delegate_job.status = JobStatus.PAUSED

    # Resume forwards to delegate
    parent_job.resume()
    await asyncio.sleep(0.01)
    assert delegate_job.status == JobStatus.RESUMING