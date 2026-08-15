import asyncio
from datetime import datetime as real_datetime
from pathlib import Path
from typing import Any, Optional

import pytest
from pydantic import BaseModel

import datorum.plumbing.worker as worker_mod
from datorum.context.settings import (
    ContextBind,
    ContextBindType,
    DocumentContext,
    ResourceBind,
)
from datorum.plumbing.exceptions import PipelineWorkerError
from datorum.plumbing.settings import (
    AgentStep,
    DecisionStep,
    HumanInteractionStep,
    Pipeline,
    PipeFlow,
    PipeFlowState,
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
) -> PipelineWorker:
    flow_dir = tmp_path / "flows"
    flow_dir.mkdir(exist_ok=True)
    worker = PipelineWorker(
        flow_settings_path=flow_dir,
        agent_worker=agent_worker or _StubWorker(),
        tool_worker=tool_worker or _StubWorker(),
    )
    return worker


def _pipeflow_job(pipeflow_id: str, job_id: str = "job1") -> Job:
    return Job(
        id=job_id,
        resource_bindings=[
            ResourceBind(field_id="pipeflow", factory_name="pipeflow", selector=pipeflow_id)
        ],
    )


def _override_pipeflow_resource(worker: PipelineWorker):
    """The built-in `pipeflow` resource factory relies on a `self.plumbing_kit`
    attribute that PipelineWorker never sets (see test_pipeflow_resource_*
    below for coverage of that bug) - so, similar to how the AgentWorker
    tests stub out `api_key`, tests that need a *working* pipeflow lookup
    override the factory to resolve from `worker.flows` instead."""
    @worker.resource(name="pipeflow", force=True)
    def _pipeflow(flow_id: str | None):
        if not flow_id:
            raise PipelineWorkerError("Flow ID is required")
        if flow_id not in worker.flows:
            raise PipelineWorkerError(f"Flow '{flow_id}' not found")
        return worker.flows[flow_id]


class _FixedDatetime:
    """Stand-in for the `datetime` class used by create_flow(), so the
    generated flow id is deterministic and collisions can be forced."""

    _now = real_datetime(2024, 1, 1, 12, 0, 0)

    @classmethod
    def now(cls):
        return cls._now


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
# PipelineWorker.get_flow_path / create_flow / load_flow
# ==============================================================================

def test_get_flow_path(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    assert worker.get_flow_path("abc") == worker.flow_settings_path / "abc.yml"


def test_create_flow_generates_id_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_mod, "datetime", _FixedDatetime)
    worker = _make_pipeline_worker(tmp_path)
    pipeline = Pipeline(id="pipe1")

    flow = worker.create_flow(pipeline)

    assert flow.id == "pipeflow_20240101_120000"
    assert flow.pipeline is not pipeline  # deep-copied
    assert flow.pipeline.id == "pipe1"
    assert worker.flows[flow.id] is flow
    assert worker.get_flow_path(flow.id).exists()


def test_create_flow_resolves_id_collisions(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_mod, "datetime", _FixedDatetime)
    worker = _make_pipeline_worker(tmp_path)
    pipeline = Pipeline(id="pipe1")

    first = worker.create_flow(pipeline)
    second = worker.create_flow(pipeline)

    assert first.id == "pipeflow_20240101_120000"
    assert second.id == "pipeflow_20240101_120000_0"
    assert worker.flows[second.id] is second


def test_load_flow_success(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    pipeline = Pipeline(id="pipe1")
    created = worker.create_flow(pipeline)
    worker.flows.clear()

    loaded = worker.load_flow(created.id)

    assert loaded.id == created.id
    assert worker.flows[created.id] is loaded


def test_load_flow_not_found(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    with pytest.raises(PipelineWorkerError, match="Pipe flow 'missing' not found"):
        worker.load_flow("missing")


# ==============================================================================
# Built-in `pipeflow` resource factory
# ==============================================================================

def test_pipeflow_resource_requires_flow_id(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    with pytest.raises(PipelineWorkerError, match="Flow ID is required"):
        worker.factories["pipeflow"](None)


def test_pipeflow_resource_unknown_flow(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    with pytest.raises(PipelineWorkerError, match="Flow 'missing' not found"):
        worker.factories["pipeflow"]("missing")


def test_pipeflow_resource_known_flow(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    flow = worker.create_flow(Pipeline(id="pipe1"))
    assert worker.factories["pipeflow"](flow.id).pipeline.id == "pipe1"


# ==============================================================================
# PipelineWorker.work() - generic flow control
# ==============================================================================

@pytest.mark.asyncio
async def test_work_unknown_step_raises(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    pipeline = Pipeline(id="pipe1", first_step_id="missing-step")
    flow = worker.create_flow(pipeline)

    job = _pipeflow_job(flow.id)
    with pytest.raises(PipelineWorkerError, match="Step 'missing-step' not found in Pipeline 'pipe1'"):
        await worker.run(job)

    assert job.status == JobStatus.CRASHED
    assert flow.state == PipeFlowState.started


@pytest.mark.asyncio
async def test_work_recovers_non_planning_flow(tmp_path):
    """When a flow is loaded mid-flight (state != planning), work() should
    resume from `current_step_id` rather than reset to `first_step_id`."""
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    step = HumanInteractionStep(id="only", chat_history=ContextBind(field_id="chat_history", binded_id="doc1"))
    pipeline = Pipeline(id="pipe1", first_step_id="unused", steps={"only": step})
    flow = worker.create_flow(pipeline)
    flow.state = PipeFlowState.paused
    flow.current_step_id = "only"

    job = _pipeflow_job(flow.id)
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, JobStatus.PAUSED)
    job.resume()
    await asyncio.wait_for(task, timeout=2)

    assert job.status == JobStatus.FINISHED
    assert flow.step_history == ["only"]


async def _wait_for_status(job: Job, status: JobStatus, timeout: float = 2.0):
    async def _poll():
        while job.status != status:
            await asyncio.sleep(0.005)
    await asyncio.wait_for(_poll(), timeout=timeout)


# ==============================================================================
# PipelineWorker.work() - HumanInteractionStep
# ==============================================================================

@pytest.mark.asyncio
async def test_work_human_interaction_step_pauses_then_resumes(tmp_path):
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    step = HumanInteractionStep(id="in", chat_history=ContextBind(field_id="chat_history", binded_id="doc1"))
    pipeline = Pipeline(id="pipe1", first_step_id="in", steps={"in": step})
    flow = worker.create_flow(pipeline)

    job = _pipeflow_job(flow.id)
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, JobStatus.PAUSED)
    assert flow.state == PipeFlowState.paused

    job.resume()
    await asyncio.wait_for(task, timeout=2)

    assert job.status == JobStatus.FINISHED
    assert flow.step_history == ["in"]
    assert flow.current_step_id is None  # step had no target_id


# ==============================================================================
# PipelineWorker.work() - ToolStep
# ==============================================================================

@pytest.mark.asyncio
async def test_work_tool_step_delegates_to_tool_worker(tmp_path):
    tool_worker = _StubWorker()
    worker = _make_pipeline_worker(tmp_path, tool_worker=tool_worker)
    _override_pipeflow_resource(worker)

    step = ToolStep(
        id="run_tool",
        target_id=None,
        tool_params=ContextBind(field_id="tool_params", binded_id="doc1"),
        tool_result=ContextBind(field_id="tool_result", binded_id="doc1"),
        toolbox_setup=ResourceBind(field_id="toolbox_setup", factory_name="toolbox_setup", selector="box1.tool1"),
    )
    pipeline = Pipeline(id="pipe1", first_step_id="run_tool", steps={"run_tool": step})
    flow = worker.create_flow(pipeline)

    job = _pipeflow_job(flow.id)
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert len(tool_worker.calls) == 1
    assert len(job.delegates) == 1
    delegate = job.delegates[0]
    assert [b.field_id for b in delegate.context_bindings] == ["tool_params", "tool_result"]
    assert delegate.resource_bindings[0].selector == "box1.tool1"
    assert flow.step_history == ["run_tool"]
    assert flow.current_step_id is None


@pytest.mark.asyncio
async def test_work_tool_step_includes_custom_context_and_resources(tmp_path):
    tool_worker = _StubWorker()
    worker = _make_pipeline_worker(tmp_path, tool_worker=tool_worker)
    _override_pipeflow_resource(worker)

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
    flow = worker.create_flow(pipeline)

    job = _pipeflow_job(flow.id)
    await worker.run(job)

    # NOTE: comparing the ContextBind/ResourceBind instances directly (e.g.
    # `extra_ctx in delegate.context_bindings`) is unreliable here: create_flow()
    # deep-copies the pipeline, and pydantic's default __eq__ also compares
    # private attrs, so the copy (with `_persistent` set) never equals the
    # original standalone instance even though their public fields match.
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
    worker = _make_pipeline_worker(tmp_path, agent_worker=agent_worker)
    _override_pipeflow_resource(worker)

    step = AgentStep(
        id="ask",
        chat_history=ContextBind(field_id="chat_history", binded_id="chat_doc"),
        inference_provider=ResourceBind(field_id="inference_provider", factory_name="inference_provider", selector="p1"),
        agent_role=ResourceBind(field_id="agent_role", factory_name="agent_role", selector="r1"),
    )
    pipeline = Pipeline(id="pipe1", first_step_id="ask", steps={"ask": step})
    flow = worker.create_flow(pipeline)

    job = _pipeflow_job(flow.id)
    await worker.run(job)

    assert job.status == JobStatus.FINISHED
    assert len(agent_worker.calls) == 1
    delegate = job.delegates[0]
    assert delegate.context_bindings[0].binded_id == "chat_doc"
    assert {b.selector for b in delegate.resource_bindings} == {"p1", "r1"}
    assert flow.step_history == ["ask"]


# ==============================================================================
# PipelineWorker.work() - DecisionStep
# ==============================================================================

def _decision_pipeline(step: DecisionStep) -> Pipeline:
    return Pipeline(id="pipe1", first_step_id="decide", steps={"decide": step})


@pytest.mark.asyncio
async def test_work_decision_step_invalid_input_type_raises(tmp_path):
    ctx = _make_context(tmp_path)
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    worker.contexts[ctx.id] = ctx

    doc = ctx.create_document(id="raw", doc_type="text/plain", doc_model="text")
    doc.save("just some text")

    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="raw", context_bind_type=ContextBindType.text),
        target_options=["a"],
    )
    flow = worker.create_flow(_decision_pipeline(step))

    job = _pipeflow_job(flow.id)
    with pytest.raises(PipelineWorkerError, match="Invalid data input type"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_decision_step_success_with_model_input(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    worker.contexts[ctx.id] = ctx

    from datorum.context.registry import register_pydantic_based_handler
    register_pydantic_based_handler(model_type=DecisionInput, model_id="decision-input")

    doc = ctx.create_document(id="decision_in", doc_type="application/json", doc_model="decision-input")
    doc.save(DecisionInput(score=7))

    fake_ctx = _FakeMPContext(queue_items=[("ok", "route_a")], alive_after_join=False)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="decision_in"),
        target_options=["route_a", "route_b"],
        code="input_data['score'] > 5",
    )
    route_a = HumanInteractionStep(
        id="route_a", chat_history=ContextBind(field_id="chat_history", binded_id="doc1")
    )
    pipeline = Pipeline(
        id="pipe1", first_step_id="decide",
        steps={"decide": step, "route_a": route_a},
    )
    flow = worker.create_flow(pipeline)

    job = _pipeflow_job(flow.id)
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, JobStatus.PAUSED)  # route_a is a HumanInteractionStep
    job.resume()
    await asyncio.wait_for(task, timeout=2)

    assert job.status == JobStatus.FINISHED
    assert flow.step_history == ["decide", "route_a"]
    assert len(fake_ctx.processes) == 1
    assert fake_ctx.processes[0].started


@pytest.mark.asyncio
async def test_work_decision_step_process_error_raises(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    worker.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"x": 1})

    fake_ctx = _FakeMPContext(queue_items=[("error", "boom")], alive_after_join=False)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["a"],
        code="1",
    )
    flow = worker.create_flow(_decision_pipeline(step))

    job = _pipeflow_job(flow.id)
    with pytest.raises(PipelineWorkerError, match="Process error reported: boom"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_decision_step_timeout_raises(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    worker.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"x": 1})

    fake_ctx = _FakeMPContext(queue_items=[], alive_after_join=True)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["a"],
        code="1",
    )
    flow = worker.create_flow(_decision_pipeline(step))

    job = _pipeflow_job(flow.id)
    with pytest.raises(PipelineWorkerError, match=r"Timed out after 5\.0s"):
        await worker.run(job)

    assert fake_ctx.processes[0].terminated


@pytest.mark.asyncio
async def test_work_decision_step_empty_queue_raises(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    worker.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"x": 1})

    fake_ctx = _FakeMPContext(queue_items=[], alive_after_join=False, exitcode=-9)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["a"],
        code="1",
    )
    flow = worker.create_flow(_decision_pipeline(step))

    job = _pipeflow_job(flow.id)
    with pytest.raises(PipelineWorkerError, match=r"Process exited without a result \(exit code -9\)"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_decision_step_invalid_target_option_raises(tmp_path, monkeypatch):
    ctx = _make_context(tmp_path)
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    worker.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"x": 1})

    fake_ctx = _FakeMPContext(queue_items=[("ok", "not_an_option")], alive_after_join=False)
    monkeypatch.setattr(worker_mod, "_MP_CONTEXT", fake_ctx)

    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["a", "b"],
        code="1",
    )
    flow = worker.create_flow(_decision_pipeline(step))

    job = _pipeflow_job(flow.id)
    with pytest.raises(PipelineWorkerError, match="Target step 'not_an_option' is not a valid option"):
        await worker.run(job)


@pytest.mark.asyncio
async def test_work_decision_step_real_subprocess_execution(tmp_path):
    """One end-to-end smoke test using the real (spawn) multiprocessing
    context, to prove `_run_code` genuinely works across a process
    boundary and not just when called in-process."""
    ctx = _make_context(tmp_path)
    worker = _make_pipeline_worker(tmp_path)
    _override_pipeflow_resource(worker)
    worker.contexts[ctx.id] = ctx
    doc = ctx.create_document(id="d", doc_type="application/json", doc_model="dict")
    doc.save({"score": 10})

    step = DecisionStep(
        id="decide",
        input_data=ContextBind(field_id="input_data", binded_id="d"),
        target_options=["big", "small"],
        code="'big' if input_data['score'] > 5 else 'small'",
    )
    big = HumanInteractionStep(
        id="big", chat_history=ContextBind(field_id="chat_history", binded_id="doc1")
    )
    pipeline = Pipeline(
        id="pipe1", first_step_id="decide",
        steps={"decide": step, "big": big},
    )
    flow = worker.create_flow(pipeline)

    job = _pipeflow_job(flow.id)
    task = asyncio.create_task(worker.run(job))
    await _wait_for_status(job, JobStatus.PAUSED)
    job.resume()
    await asyncio.wait_for(task, timeout=2)

    assert job.status == JobStatus.FINISHED
    assert flow.step_history == ["decide", "big"]