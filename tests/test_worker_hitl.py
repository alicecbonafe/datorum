"""Covers the pause/resume mechanics of PipelineWorker.work() for
HumanInteractionStep, end to end against real Job/Binder/Worker objects
(no mocks) since the behavior hinges on real asyncio scheduling."""
import asyncio
from pathlib import Path

import pytest

import datorum
from datorum.binding.settings import ContextBind
from datorum.plumbing.settings import HumanInteractionStep, Pipeline, ToolStep
from datorum.plumbing.worker import PipelineWorker
from datorum.tooling.worker import ToolWorker
from datorum.agency.worker import AgentWorker


@pytest.fixture
def flows_path(tmp_path: Path) -> Path:
    return tmp_path / "flows"


@pytest.fixture
def workers(flows_path):
    binder = datorum.Binder()
    tool_worker = ToolWorker(binder=binder, toolkit=datorum.ToolKit())
    agent_worker = AgentWorker(binder=binder, agencykit=datorum.AgencyKit(), tool_worker=tool_worker)
    return binder, tool_worker, agent_worker


def _hitl_pipeline(target_id=None) -> Pipeline:
    return Pipeline(
        id="hitl-test",
        first_step_id="in",
        steps={
            "in": HumanInteractionStep(
                id="in",
                interactive=ContextBind(
                    field_id="interactive",
                    binded_id="chat",
                    context="ctx",
                ),
                target_id=target_id,
            ),
        },
    )


def _make_worker(workers, pipeline: Pipeline, flows_path: Path) -> tuple[PipelineWorker, datorum.PipeFlow]:
    binder, tool_worker, agent_worker = workers
    plumbingkit = datorum.PlumbingKit(pipelines={pipeline.id: pipeline})
    worker = PipelineWorker(
        binder=binder, plumbingkit=plumbingkit, agent_worker=agent_worker, tool_worker=tool_worker,
    )
    worker.register_flow_factories(flow_path=flows_path, flow_id_template="flow_{index}")
    pipeflow = worker.create_flow(pipeline.id)
    return worker, pipeflow


def _job_for(pipeflow: datorum.PipeFlow) -> datorum.Job:
    return datorum.Job(
        id=f"job_{pipeflow.id}",
        resource_bindings=[
            datorum.ResourceBind(field_id="pipeflow", factory_name="restore_pipeflow", selector=pipeflow.id),
        ],
    )


async def _run_until_paused(worker: PipelineWorker, job: datorum.Job, timeout: float = 2.0) -> asyncio.Task:
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, datorum.JobStatus.PAUSED, timeout=timeout, task=task)
    return task


async def _wait_for_status(
    job: datorum.Job, status: datorum.JobStatus, timeout: float = 2.0, task: asyncio.Task | None = None,
) -> None:
    for _ in range(int(timeout / 0.01)):
        if job.status == status:
            return
        if task is not None and task.done():
            # let a crash surface with its real traceback instead of timing out
            task.result()
        await asyncio.sleep(0.01)
    raise AssertionError(f"Job never reached {status} (stuck at {job.status})")


class TestHumanInteractionPause:
    @pytest.mark.asyncio
    async def test_pauses_and_registers_interactive_binding(self, workers, flows_path):
        worker, pipeflow = _make_worker(workers, _hitl_pipeline(), flows_path)
        job = _job_for(pipeflow)

        task = await _run_until_paused(worker, job)

        assert pipeflow.state == datorum.PipeFlowState.paused
        interactive = next(b for b in job.context_bindings if b.field_id == "interactive")
        assert interactive.binded_id == "chat"
        assert interactive.context == "ctx"
        assert interactive.context_bind_type == datorum.ContextBindType.model

        job.resume()
        await task
        assert job.status == datorum.JobStatus.FINISHED
        assert pipeflow.state == datorum.PipeFlowState.finished

    @pytest.mark.asyncio
    async def test_does_not_advance_before_resume(self, workers, flows_path):
        """Regression guard: the job must genuinely block at PAUSED, not just
        log a message and continue -- this is the exact bug that was fixed."""
        worker, pipeflow = _make_worker(workers, _hitl_pipeline(target_id="unreachable"), flows_path)
        job = _job_for(pipeflow)

        task = await _run_until_paused(worker, job)
        await asyncio.sleep(0.05)

        assert job.status == datorum.JobStatus.PAUSED
        assert pipeflow.current_step_id == "in"

        job.resume()
        with pytest.raises(datorum.PipelineWorkerError):
            await task

    @pytest.mark.asyncio
    async def test_second_pause_updates_existing_binding_in_place(self, workers, flows_path):
        """Two HITL steps in one flow: the second pause must update the
        existing 'interactive' binding rather than appending a duplicate."""
        pipeline = Pipeline(
            id="hitl-twice",
            first_step_id="first",
            steps={
                "first": HumanInteractionStep(
                    id="first", target_id="second",
                    interactive=ContextBind(field_id="interactive", binded_id="chat-1", context="ctx-a"),
                ),
                "second": HumanInteractionStep(
                    id="second", target_id=None,
                    interactive=ContextBind(field_id="interactive", binded_id="chat-2", context="ctx-b"),
                ),
            },
        )
        worker, pipeflow = _make_worker(workers, pipeline, flows_path)
        job = _job_for(pipeflow)

        task = await _run_until_paused(worker, job)
        first_bind = next(b for b in job.context_bindings if b.field_id == "interactive")
        assert first_bind.binded_id == "chat-1"
        assert pipeflow.current_step_id == "first"

        job.resume()
        # The whole resume -> next-step -> re-pause cycle can complete within
        # a single poll tick, so watching for status to leave PAUSED and come
        # back is racy. current_step_id is the reliable signal here.
        for _ in range(200):
            if pipeflow.current_step_id == "second" and job.status == datorum.JobStatus.PAUSED:
                break
            if task.done():
                task.result()
            await asyncio.sleep(0.01)
        else:
            raise AssertionError(f"never reached the second pause (stuck at step {pipeflow.current_step_id!r})")

        bindings = [b for b in job.context_bindings if b.field_id == "interactive"]
        assert len(bindings) == 1, "second pause must not append a duplicate binding"
        assert bindings[0].binded_id == "chat-2"
        assert bindings[0].context == "ctx-b"

        job.resume()
        await task
        assert job.status == datorum.JobStatus.FINISHED
