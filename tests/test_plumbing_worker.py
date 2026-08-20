import asyncio
from pathlib import Path
from typing import Any, Optional

import pytest
from pydantic import BaseModel

import datorum.plumbing.worker as worker_mod
from datorum.binding.binder import Binder
from datorum.binding.settings import (
    ContextBind,
    ContextBindType,
    ResourceBind,
)
from datorum.context.settings import (
    DocumentContext,
)
from datorum.plumbing.exceptions import PipelineWorkerError
from datorum.plumbing.settings import (
    AgentStep,
    DecisionStep,
    HumanInteractionStep,
    Pipeline,
    PipeFlow,
    PipeFlowState,
    PlumbingKit,
    ToolStep,
)
from datorum.plumbing.worker import (
    PipelineWorker,
    _restricted_globals,
    _run_code,
)
from datorum.work.job import Job, JobStatus


# ==============================================================================
# Fixtures / helpers
# ==============================================================================

def _make_context(tmp_path: Path, ctx_id: str = "ctx1") -> DocumentContext:
    ctx = DocumentContext(id=ctx_id)
    ctx.save_as(tmp_path / f"{ctx_id}.yml")
    return ctx


class _StubWorker:
    """Duck-typed stand-in for AgentWorker/ToolWorker: PipelineWorker only
    ever calls `.run(job)` on its collaborators, so a minimal async stub is
    enough to unit-test the pipeline orchestration in isolation."""

    def __init__(self, on_run=None):
        self.calls: list[Job] = []
        self._on_run = on_run

    async def run(self, job: Job):
        self.calls.append(job)
        if self._on_run is not None:
            await self._on_run(job)
        else:
            await job.update_status(JobStatus.FINISHED, "stub finished")


def _make_pipeline_worker(
    tmp_path: Path,
    agent_worker: Optional[_StubWorker] = None,
    tool_worker: Optional[_StubWorker] = None,
    plumbingkit: Optional[PlumbingKit] = None,
    flow_id_template: str = "flow_{index}",
) -> PipelineWorker:
    """Builds a PipelineWorker wired the way the application layer wires it:
    construct with a PlumbingKit, then separately call
    register_flow_factories() to hook up `create_pipeflow`/`restore_pipeflow`
    against a directory on disk."""
    binder: Binder = Binder()
    worker = PipelineWorker(
        binder=binder,
        plumbingkit=plumbingkit or PlumbingKit(),
        agent_worker=agent_worker or _StubWorker(),
        tool_worker=tool_worker or _StubWorker(),
    )
    flow_dir = tmp_path / "flows"
    flow_dir.mkdir(exist_ok=True)
    worker.register_flow_factories(flow_dir, flow_id_template=flow_id_template)
    return worker


def _create_job(pipeline_id: str, job_id: str = "job1") -> Job:
    """Job bound to create a fresh PipeFlow from a Pipeline in the kit."""
    return Job(
        id=job_id,
        resource_bindings=[
            ResourceBind(field_id="pipeflow", factory_name="create_pipeflow", selector=pipeline_id)
        ],
    )


def _restore_job(flow_id: str, job_id: str = "job1") -> Job:
    """Job bound to resume a previously-created PipeFlow from disk."""
    return Job(
        id=job_id,
        resource_bindings=[
            ResourceBind(field_id="pipeflow", factory_name="restore_pipeflow", selector=flow_id)
        ],
    )


class _FakeQueue:
    def __init__(self, items: Optional[list] = None):
        self._items = list(items or [])

    def empty(self) -> bool:
        return len(self._items) == 0

    def get(self):
        return self._items.pop(0)

    def put(self, item):
        self._items.append(item)


class _FakeProcess:
    def __init__(self, target, args, daemon=True, alive_after_join=False, exitcode=1):
        self.target = target
        self.args = args
        self.daemon = daemon
        self._alive_after_join = alive_after_join
        self.exitcode = exitcode
        self.terminated = False
        self.started = False

    def start(self):
        self.started = True

    def join(self, timeout=None):
        pass

    def is_alive(self) -> bool:
        return self._alive_after_join

    def terminate(self):
        self.terminated = True
        self._alive_after_join = False


class _FakeMPContext:
    """Stands in for the real (spawn) multiprocessing context so
    DecisionStep orchestration can be tested deterministically and fast,
    without actually spawning subprocesses."""

    def __init__(self, queue_items=None, alive_after_join=False, exitcode=1):
        self._queue_items = queue_items
        self._alive_after_join = alive_after_join
        self._exitcode = exitcode
        self.processes: list[_FakeProcess] = []

    def Queue(self):
        return _FakeQueue(self._queue_items)

    def Process(self, target, args, daemon=True):
        process = _FakeProcess(
            target=target, args=args, daemon=daemon,
            alive_after_join=self._alive_after_join,
            exitcode=self._exitcode,
        )
        self.processes.append(process)
        return process


class DecisionInput(BaseModel):
    score: int


async def _wait_for_status(job: Job, status: JobStatus, timeout: float = 2.0):
    async def _poll():
        while job.status != status:
            await asyncio.sleep(0.005)
    await asyncio.wait_for(_poll(), timeout=timeout)


# ==============================================================================
# _restricted_globals / _run_code
# ==============================================================================

def test_restricted_globals_has_expected_keys():
    g = _restricted_globals()
    assert "_getattr_" in g
    assert "_getitem_" in g
    assert "_getiter_" in g
    assert "_iter_unpack_sequence_" in g
    assert "_unpack_sequence_" in g


def test_run_code_formula_success():
    q = _FakeQueue()
    _run_code("input_data['score'] + 1", "formula", {"score": 41}, q)
    assert q.get() == ("ok", 42)


def test_run_code_formula_syntax_error():
    q = _FakeQueue()
    _run_code("def(", "formula", {}, q)
    status, message = q.get()
    assert status == "error"
    assert "SyntaxError" in message


def test_run_code_snippet_success():
    q = _FakeQueue()
    code = "target = input_data['a'] + input_data['b']"
    _run_code(code, "snippet", {"a": 2, "b": 3}, q)
    assert q.get() == ("ok", 5)


def test_run_code_snippet_missing_target_assignment():
    q = _FakeQueue()
    _run_code("x = 1", "snippet", {}, q)
    status, message = q.get()
    assert status == "error"
    assert "NameError" in message
    assert "target" in message


def test_run_code_snippet_syntax_error():
    q = _FakeQueue()
    _run_code("def(", "snippet", {}, q)
    status, message = q.get()
    assert status == "error"
    assert "SyntaxError" in message


def test_run_code_runtime_exception_is_captured():
    q = _FakeQueue()
    _run_code("1 / 0", "formula", {}, q)
    status, message = q.get()
    assert status == "error"
    assert "ZeroDivisionError" in message


# ==============================================================================
# register_flow_factories / create_pipeflow / restore_pipeflow
#
# NOTE: `_create_pipeflow` closes over `last_index` and reassigns it
# (`last_index = index`) without a `nonlocal last_index` declaration. That
# assignment makes Python treat `last_index` as local to `_create_pipeflow`
# for the *whole* function body, so the earlier read (`index = last_index + 1`)
# raises `UnboundLocalError` on every call - `create_pipeflow` is currently
# broken, even on the very first invocation. These tests assume that's fixed
# by adding `nonlocal last_index` at the top of `_create_pipeflow`; until
# that's patched, every test in this section (and anything in "PipelineWorker
# .work()" that goes through `create_pipeflow`) will fail with
# UnboundLocalError rather than the assertions below.
# ==============================================================================

def test_register_flow_factories_registers_create_and_restore(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    assert "create_pipeflow" in worker.binder.factories
    assert "restore_pipeflow" in worker.binder.factories


def test_create_pipeflow_requires_pipeline_id(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    with pytest.raises(PipelineWorkerError, match="Pipeline ID is required"):
        worker.binder.factories["create_pipeflow"](None)


def test_create_pipeflow_unknown_pipeline(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    with pytest.raises(PipelineWorkerError, match="Pipeline 'missing' not found"):
        worker.binder.factories["create_pipeflow"]("missing")


def test_create_pipeflow_generates_id_and_persists(tmp_path):
    pipeline = Pipeline(id="pipe1")
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )

    flow = worker.binder.factories["create_pipeflow"]("pipe1")

    assert flow.id == "flow_0"
    assert flow.pipeline is not pipeline  # deep-copied
    assert flow.pipeline.id == "pipe1"
    assert (tmp_path / "flows" / "flow_0.yml").exists()


def test_create_pipeflow_resolves_id_collisions(tmp_path):
    pipeline = Pipeline(id="pipe1")
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )

    first = worker.binder.factories["create_pipeflow"]("pipe1")
    second = worker.binder.factories["create_pipeflow"]("pipe1")

    assert first.id == "flow_0"
    assert second.id == "flow_1"


def test_create_pipeflow_skips_index_of_preexisting_file_on_disk(tmp_path):
    """If a flow file already exists on disk for the next candidate index
    (e.g. left over from a previous run), create_pipeflow should skip past
    it rather than overwrite it."""
    pipeline = Pipeline(id="pipe1")
    flow_dir = tmp_path / "flows"
    flow_dir.mkdir(exist_ok=True)
    (flow_dir / "flow_0.yml").write_text("id: flow_0\npipeline: {id: other}\n")

    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )

    flow = worker.binder.factories["create_pipeflow"]("pipe1")
    assert flow.id == "flow_1"


def test_create_pipeflow_respects_custom_id_template(tmp_path):
    pipeline = Pipeline(id="pipe1")
    worker = _make_pipeline_worker(
        tmp_path,
        plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline}),
        flow_id_template="pf_{index}_run",
    )

    flow = worker.binder.factories["create_pipeflow"]("pipe1")
    assert flow.id == "pf_0_run"
    assert (tmp_path / "flows" / "pf_0_run.yml").exists()


def test_create_pipeflow_resolves_runtime_collision_with_uncached_file(tmp_path):
    """If a flow file appears on disk for the freshly-computed candidate index
    *after* register_flow_factories() has already scanned the directory (so
    it's on disk but not in the in-memory flow_files cache), create_pipeflow's
    collision loop should still skip past it rather than overwrite it."""
    pipeline = Pipeline(id="pipe1")
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )
    # Simulate a flow file that shows up after registration's initial disk
    # scan (e.g. written by another process), so it's unknown to flow_files.
    (tmp_path / "flows" / "flow_0.yml").write_text(
        "id: flow_0\npipeline: {id: other}\n"
    )

    flow = worker.binder.factories["create_pipeflow"]("pipe1")

    assert flow.id == "flow_1"
    assert (tmp_path / "flows" / "flow_1.yml").exists()


def test_restore_pipeflow_requires_flow_id(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    with pytest.raises(PipelineWorkerError, match="Pipeflow ID is required"):
        worker.binder.factories["restore_pipeflow"](None)


def test_restore_pipeflow_unknown_flow(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    with pytest.raises(PipelineWorkerError, match="Pipeflow 'missing' not found"):
        worker.binder.factories["restore_pipeflow"]("missing")


def test_restore_pipeflow_loads_created_flow(tmp_path):
    pipeline = Pipeline(id="pipe1")
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )
    created = worker.binder.factories["create_pipeflow"]("pipe1")

    restored = worker.binder.factories["restore_pipeflow"](created.id)

    assert restored.id == created.id
    assert restored.pipeline.id == "pipe1"


def test_restore_pipeflow_finds_flow_file_not_yet_seen_this_session(tmp_path):
    """A flow file written in an earlier process/session (so it's not in the
    in-memory `flow_files` cache yet) should still be discoverable by id."""
    flow_dir = tmp_path / "flows"
    flow_dir.mkdir(exist_ok=True)
    pipeline = Pipeline(id="pipe1")
    flow = PipeFlow(id="flow_7", pipeline=pipeline)
    flow.save_as(flow_dir / "flow_7.yml")

    worker = _make_pipeline_worker(tmp_path)
    restored = worker.binder.factories["restore_pipeflow"]("flow_7")
    assert restored.id == "flow_7"


def test_restore_pipeflow_caches_file_discovered_after_registration(tmp_path):
    """A flow file written *after* register_flow_factories() already scanned
    the directory (so it's missing from the initial flow_files population)
    should still be found by id on first lookup, get added to the in-memory
    flow_files cache, and be served straight from the flow cache afterwards."""
    worker = _make_pipeline_worker(tmp_path)
    flow_dir = tmp_path / "flows"
    pipeline = Pipeline(id="pipe1")
    flow = PipeFlow(id="flow_9", pipeline=pipeline)
    flow.save_as(flow_dir / "flow_9.yml")

    restored = worker.binder.factories["restore_pipeflow"]("flow_9")
    assert restored.id == "flow_9"

    restored_again = worker.binder.factories["restore_pipeflow"]("flow_9")
    assert restored_again is restored


def test_create_flow_delegates_to_create_pipeflow_resource(tmp_path):
    pipeline = Pipeline(id="pipe1")
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )

    flow = worker.create_flow("pipe1")

    assert flow.id == "flow_0"
    assert flow.pipeline.id == "pipe1"
    assert (tmp_path / "flows" / "flow_0.yml").exists()


# ==============================================================================
# PipelineWorker.work() - generic flow control
# ==============================================================================

@pytest.mark.asyncio
async def test_work_requires_create_or_restore_binding(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    job = Job(id="job1")  # no resource_bindings at all

    with pytest.raises(
        PipelineWorkerError,
        match="Required binding not provided for 'create_pipeflow' or 'restore_pipeflow'",
    ):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_unknown_step_raises(tmp_path):
    pipeline = Pipeline(id="pipe1", first_step_id="missing-step")
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )

    job = _create_job("pipe1")
    with pytest.raises(PipelineWorkerError, match="Step 'missing-step' not found in Pipeline 'pipe1'"):
        await worker.run(job)

    assert job.status == JobStatus.CRASHED


@pytest.mark.asyncio
async def test_work_recovers_non_planning_flow(tmp_path):
    """When a flow is restored mid-flight (state != planning), work() should
    resume from `current_step_id` rather than reset to `first_step_id`."""
    step = HumanInteractionStep(id="only", interactive_document_id="doc1")
    pipeline = Pipeline(id="pipe1", first_step_id="unused", steps={"only": step})
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )

    created = worker.binder.factories["create_pipeflow"]("pipe1")
    # simulate a flow that was already mid-run and persisted in that state
    created.state = PipeFlowState.paused
    created.current_step_id = "only"
    created.save()

    job = _restore_job(created.id)
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, JobStatus.PAUSED)
    job.resume()
    await asyncio.wait_for(task, timeout=2)

    assert job.status == JobStatus.FINISHED
    assert created.step_history == ["only"]


@pytest.mark.asyncio
async def test_work_active_flow_tracked_and_released(tmp_path):
    step = ToolStep(
        id="in",
        target_id=None,
        tool_params=ContextBind(field_id="tool_params", binded_id="doc1"),
        tool_result=ContextBind(field_id="tool_result", binded_id="doc1"),
        toolbox_setup=ResourceBind(field_id="toolbox_setup", factory_name="toolbox_setup", selector="box1.tool1"),
    )
    pipeline = Pipeline(id="pipe1", steps={"in": step})
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )

    job = _create_job("pipe1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert worker._active_flows == {}  # released once the flow finishes


@pytest.mark.asyncio
async def test_work_rejects_concurrent_run_of_same_pipeflow(tmp_path):
    step = HumanInteractionStep(id="in", interactive_document_id="doc1", interactive_document_context=None)
    pipeline = Pipeline(id="pipe1", first_step_id="in", steps={"in": step})
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )
    created = worker.binder.factories["create_pipeflow"]("pipe1")

    job1 = _restore_job(created.id, job_id="job1")
    task1 = asyncio.create_task(worker.run(job1))
    await _wait_for_status(job1, JobStatus.PAUSED)

    job2 = _restore_job(created.id, job_id="job2")
    with pytest.raises(PipelineWorkerError, match=f"Pipeflow '{created.id}' already running in job 'job1'"):
        await worker.run(job2)

    job1.resume()
    await asyncio.wait_for(task1, timeout=2)
    assert worker._active_flows == {}


# ==============================================================================
# PipelineWorker.work() - HumanInteractionStep
# ==============================================================================

@pytest.mark.asyncio
async def test_work_human_interaction_step_pauses_then_resumes(tmp_path):
    step = HumanInteractionStep(id="in", interactive_document_id="doc1", interactive_document_context=None)
    pipeline = Pipeline(id="pipe1", first_step_id="in", steps={"in": step})
    worker = _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )
    created = worker.binder.factories["create_pipeflow"]("pipe1")

    job = _restore_job(created.id)
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, JobStatus.PAUSED)

    job.resume()
    await asyncio.wait_for(task, timeout=2)

    assert job.status == JobStatus.FINISHED
    assert created.step_history == ["in"]
    assert created.current_step_id is None  # step had no target_id


# ==============================================================================
# PipelineWorker.work() - ToolStep
# ==============================================================================

@pytest.mark.asyncio
async def test_work_tool_step_delegates_to_tool_worker(tmp_path):
    tool_worker = _StubWorker()
    step = ToolStep(
        id="run_tool",
        target_id=None,
        tool_params=ContextBind(field_id="tool_params", binded_id="doc1"),
        tool_result=ContextBind(field_id="tool_result", binded_id="doc1"),
        toolbox_setup=ResourceBind(field_id="toolbox_setup", factory_name="toolbox_setup", selector="box1.tool1"),
    )
    pipeline = Pipeline(id="pipe1", first_step_id="run_tool", steps={"run_tool": step})
    worker = _make_pipeline_worker(
        tmp_path, tool_worker=tool_worker,
        plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline}),
    )

    job = _create_job("pipe1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert len(tool_worker.calls) == 1
    assert len(job.delegates) == 1
    delegate = job.delegates[0]
    assert [b.field_id for b in delegate.context_bindings] == ["tool_params", "tool_result"]
    assert delegate.resource_bindings[0].selector == "box1.tool1"


@pytest.mark.asyncio
async def test_work_tool_step_includes_custom_context_and_resources(tmp_path):
    tool_worker = _StubWorker()
    extra_ctx = ContextBind(field_id="extra_ctx", binded_id="doc2")
    extra_res = ResourceBind(field_id="extra_res", factory_name="some_factory", selector="x")
    step = ToolStep(
        id="run_tool",
        tool_params=ContextBind(field_id="tool_params", binded_id="doc1"),
        tool_result=ContextBind(field_id="tool_result", binded_id="doc1"),
        toolbox_setup=ResourceBind(field_id="toolbox_setup", factory_name="toolbox_setup", selector="box1.tool1"),
        custom_context=[extra_ctx],
        custom_resources=[extra_res],
    )
    pipeline = Pipeline(id="pipe1", first_step_id="run_tool", steps={"run_tool": step})
    worker = _make_pipeline_worker(
        tmp_path, tool_worker=tool_worker,
        plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline}),
    )

    job = _create_job("pipe1")
    await worker.run(job)

    delegate = job.delegates[0]
    assert [b.field_id for b in delegate.context_bindings] == [
        "tool_params", "tool_result", "extra_ctx"
    ]
    assert any(b.binded_id == "doc2" for b in delegate.context_bindings)
    assert [b.field_id for b in delegate.resource_bindings] == [
        "toolbox_setup", "extra_res"
    ]
    assert any(b.selector == "x" for b in delegate.resource_bindings)


# ==============================================================================
# PipelineWorker.work() - AgentStep
# ==============================================================================

@pytest.mark.asyncio
async def test_work_agent_step_delegates_to_agent_worker(tmp_path):
    agent_worker = _StubWorker()
    step = AgentStep(
        id="ask",
        chat_history=ContextBind(field_id="chat_history", binded_id="chat_doc"),
        inference_provider=ResourceBind(field_id="inference_provider", factory_name="inference_provider", selector="p1"),
        agent_role=ResourceBind(field_id="agent_role", factory_name="agent_role", selector="r1"),
    )
    pipeline = Pipeline(id="pipe1", first_step_id="ask", steps={"ask": step})
    worker = _make_pipeline_worker(
        tmp_path, agent_worker=agent_worker,
        plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline}),
    )

    job = _create_job("pipe1")
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert len(agent_worker.calls) == 1
    delegate = job.delegates[0]
    assert delegate.context_bindings[0].binded_id == "chat_doc"
    assert {b.selector for b in delegate.resource_bindings} == {"p1", "r1"}


# ==============================================================================
# PipelineWorker.work() - DecisionStep
# ==============================================================================

def _decision_pipeline(step: DecisionStep) -> Pipeline:
    return Pipeline(id="pipe1", first_step_id="decide", steps={"decide": step})


def _decision_worker(tmp_path, pipeline: Pipeline) -> PipelineWorker:
    return _make_pipeline_worker(
        tmp_path, plumbingkit=PlumbingKit(pipelines={"pipe1": pipeline})
    )


@pytest.mark.asyncio
async def test_work_decision_step_invalid_input_type_raises(tmp_path):
    ctx = _make_context(tmp_path)
    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="raw", context_bind_type=ContextBindType.text),
        target_options=["a"],
    )
    worker = _decision_worker(tmp_path, _decision_pipeline(step))
    worker.binder.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="raw", doc_type="text/plain", doc_model="text")
    doc.save("just some text")

    job = _create_job("pipe1")
    with pytest.raises(PipelineWorkerError, match="Invalid data input type"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_decision_step_success_with_model_input(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    from datorum.context.registry import register_pydantic_based_handler
    register_pydantic_based_handler(model_type=DecisionInput, model_id="decision-input")

    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="decision_in"),
        target_options=["route_a", "route_b"],
        code="input_data['score'] > 5",
    )
    route_a = HumanInteractionStep(
        id="route_a", interactive_document_id="doc1", interactive_document_context=None,
    )
    pipeline = Pipeline(
        id="pipe1", first_step_id="decide",
        steps={"decide": step, "route_a": route_a},
    )
    worker = _decision_worker(tmp_path, pipeline)
    worker.binder.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="decision_in", doc_type="application/json", doc_model="decision-input")
    doc.save(DecisionInput(score=7))

    fake_ctx = _FakeMPContext(queue_items=[("ok", "route_a")], alive_after_join=False)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    job = _create_job("pipe1")
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, JobStatus.PAUSED)  # route_a is a HumanInteractionStep
    job.resume()
    await asyncio.wait_for(task, timeout=2)

    assert job.status == JobStatus.FINISHED
    assert len(fake_ctx.processes) == 1
    assert fake_ctx.processes[0].started


@pytest.mark.asyncio
async def test_work_decision_step_process_error_raises(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["a"],
        code="1",
    )
    worker = _decision_worker(tmp_path, _decision_pipeline(step))
    worker.binder.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"x": 1})

    fake_ctx = _FakeMPContext(queue_items=[("error", "boom")], alive_after_join=False)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    job = _create_job("pipe1")
    with pytest.raises(PipelineWorkerError, match="Process error reported: boom"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_decision_step_timeout_raises(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["a"],
        code="1",
    )
    worker = _decision_worker(tmp_path, _decision_pipeline(step))
    worker.binder.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"x": 1})

    fake_ctx = _FakeMPContext(queue_items=[], alive_after_join=True)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    job = _create_job("pipe1")
    with pytest.raises(PipelineWorkerError, match=r"Timed out after 5\.0s"):
        await worker.run(job)

    assert fake_ctx.processes[0].terminated


@pytest.mark.asyncio
async def test_work_decision_step_empty_queue_raises(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["a"],
        code="1",
    )
    worker = _decision_worker(tmp_path, _decision_pipeline(step))
    worker.binder.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"x": 1})

    fake_ctx = _FakeMPContext(queue_items=[], alive_after_join=False, exitcode=-9)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    job = _create_job("pipe1")
    with pytest.raises(PipelineWorkerError, match=r"Process exited without a result \(exit code -9\)"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_decision_step_invalid_target_option_raises(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["a", "b"],
        code="1",
    )
    worker = _decision_worker(tmp_path, _decision_pipeline(step))
    worker.binder.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"x": 1})

    fake_ctx = _FakeMPContext(queue_items=[("ok", "not_an_option")], alive_after_join=False)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    job = _create_job("pipe1")
    with pytest.raises(PipelineWorkerError, match="Target step 'not_an_option' is not a valid option"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_decision_step_real_subprocess_execution(tmp_path):
    """One end-to-end smoke test using the real (spawn) multiprocessing
    context, to prove `_run_code` genuinely works across a process
    boundary and not just when called in-process."""
    ctx = _make_context(tmp_path)
    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["big", "small"],
        code="'big' if input_data['score'] > 5 else 'small'",
    )
    big = HumanInteractionStep(
        id="big", interactive_document_id="doc1", interactive_document_context=None,
    )
    pipeline = Pipeline(
        id="pipe1", first_step_id="decide",
        steps={"decide": step, "big": big},
    )
    worker = _decision_worker(tmp_path, pipeline)
    worker.binder.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"score": 10})

    job = _create_job("pipe1")
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, JobStatus.PAUSED)
    job.resume()
    await asyncio.wait_for(task, timeout=2)

    assert job.status == JobStatus.FINISHED