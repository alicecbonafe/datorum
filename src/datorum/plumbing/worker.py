from datetime import datetime
import multiprocessing
from pathlib import Path
from typing import Optional, Any, Literal
import uuid

from pydantic import BaseModel
from RestrictedPython import compile_restricted_eval, compile_restricted_exec
from RestrictedPython import safe_globals
from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
from RestrictedPython.Guards import (
    safer_getattr,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
)

from ..agency.settings import InferenceServiceProvider, AgentRole
from ..agency.worker import AgentWorker
from ..context.settings import DocumentReference, ContextBind, ResourceBind
from ..tooling.settings import ToolBoxSetUp
from ..tooling.worker import ToolWorker
from ..work.job import Job, JobStatus
from ..work.worker import Worker
from .exceptions import PipelineWorkerError
from .settings import (
    PlumbingKit,
    Pipeline,
    PipeFlow,
    PipeFlowState,
    HumanInteractionStep,
    ToolStep,
    AgentStep,
    DecisionStep,
)


_MP_CONTEXT = multiprocessing.get_context("spawn")

_CODE_TIMEOUT: float = 5.0

_RESULT_VAR: str = "target"

def _restricted_globals() -> dict[str, Any]:
    g = dict(safe_globals)
    g["_getattr_"] = safer_getattr               # blocks `_private`/dunder access
    g["_getitem_"] = default_guarded_getitem      # input_data['field']
    g["_getiter_"] = default_guarded_getiter      # for/comprehension support
    g["_iter_unpack_sequence_"] = guarded_iter_unpack_sequence
    g["_unpack_sequence_"] = guarded_unpack_sequence
    return g

def _run_code(
    code: str,
    mode: Literal["formula", "snippet"],
    input_data: dict,
    out_queue: "multiprocessing.Queue",
) -> None:
    try:
        glb = _restricted_globals()
        if mode == "formula":
            compiled = compile_restricted_eval(code, filename=f"<{_RESULT_VAR}>")
            if compiled.errors:
                raise SyntaxError("; ".join(compiled.errors))
            result = eval(compiled.code, glb, {"input_data": input_data})
        else:
            compiled = compile_restricted_exec(code, filename=f"<{_RESULT_VAR}>")
            if compiled.errors:
                raise SyntaxError("; ".join(compiled.errors))
            loc: dict[str, Any] = {"input_data": input_data}
            exec(compiled.code, glb, loc)
            if _RESULT_VAR not in loc:
                raise NameError(f"Snippet did not assign a value to '{_RESULT_VAR}'")
            result = loc[_RESULT_VAR]
        out_queue.put(("ok", result))
    except BaseException as exc:
        out_queue.put(("error", f"{type(exc).__name__}: {exc}"))


class PipelineWorker(Worker):
    required_resource_binds: list[str] = ["pipeflow"]

    def __init__(self,
        flow_settings_path: Path,
        agent_worker: AgentWorker,
        tool_worker: ToolWorker,
    ):
        self.flow_settings_path: Path = flow_settings_path
        self.agent_worker: AgentWorker = agent_worker
        self.tool_worker: ToolWorker = tool_worker

        self.flows: dict[str, PipeFlow] = {}

        @self.resource(name="pipeflow")
        def _pipeflow(flow_id: str | None):
            if not flow_id:
                raise PipelineWorkerError("Flow ID is required")
            if flow_id not in self.flows:
                raise PipelineWorkerError(f"Flow '{flow_id}' not found")
            return self.flows[flow_id]

    def get_flow_path(self, flow_id: str) -> Path:
        return self.flow_settings_path / f"{flow_id}.yml"

    def create_flow(self, pipeline: Pipeline) -> PipeFlow:
        # TODO Should this be threadsafe?
        _flow_id = f"pipeflow_{datetime.now().strftime("%Y%m%d_%H%M%S")}"
        flow_id = _flow_id
        flow_iter = 0
        while flow_id in self.flows:
            flow_id = f"{_flow_id}_{flow_iter}"
            flow_iter += 1

        pipeline_copy: Pipeline = pipeline.model_copy(deep=True)
        pipeflow: PipeFlow = PipeFlow(
            id=flow_id,
            pipeline=pipeline_copy,
        )
        pipeflow.save_as(self.get_flow_path(flow_id))

        self.flows[flow_id] = pipeflow
        return pipeflow

    def load_flow(self, flow_id: str) -> PipeFlow:
        flow_path = self.get_flow_path(flow_id)
        if not flow_path.exists():
            raise PipelineWorkerError(f"Pipe flow '{flow_id}' not found")
        pipeflow: PipeFlow = PipeFlow.load(flow_path)

        self.flows[flow_id] = pipeflow
        return pipeflow

    async def work(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Collecting pipeflow resources")

        pipeflow_bind: ResourceBind = next(
            bind for bind in job.resource_bindings \
                if bind.field_id == "pipeflow"
        )
        pipeflow: PipeFlow = self.load_resource(pipeflow_bind)

        if pipeflow.state == PipeFlowState.planning:
            await job.update_status(JobStatus.WORKING, "Initializing pipeflow")
            pipeflow.current_step_id = pipeflow.pipeline.first_step_id
            pipeflow.state = PipeFlowState.started
            pipeflow.save()
        else:
            await job.update_status(JobStatus.WORKING, "Recovering pipeflow")
            pipeflow.state = PipeFlowState.started
            pipeflow.save()

        while pipeflow.current_step_id is not None:
            if pipeflow.current_step_id not in pipeflow.pipeline.steps:
                raise PipelineWorkerError(f"Step '{pipeflow.current_step_id}' not found in Pipeline '{pipeflow.pipeline.id}'")

            current_step = pipeflow.pipeline.steps[pipeflow.current_step_id]
            if isinstance(current_step, HumanInteractionStep):
                pipeflow.state = PipeFlowState.paused
                pipeflow.save()
                await job.update_status(JobStatus.PAUSING, "Waiting for human interaction.")
                await job.update_status(JobStatus.WORKING, "Resuming pipeflow...")

            elif isinstance(current_step, ToolStep):
                await job.update_status(JobStatus.WORKING, f"Running tool step '{pipeflow.current_step_id}'...")

                tool_job: Job = Job(
                    id=f"{job.id}_tool_{uuid.uuid4().hex[:6]}",
                    context_bindings=[
                        current_step.tool_params,
                        current_step.tool_result,
                        *current_step.custom_context
                    ],
                    resource_bindings=[
                        current_step.toolbox_setup,
                        *current_step.custom_resources
                    ]
                )
                job.delegates.append(tool_job)

                await job.update_status(JobStatus.WORKING, f"Calling tool '{current_step.toolbox_setup.selector}'")
                await self.tool_worker.run(tool_job)
                await job.update_status(JobStatus.WORKING, "Tool worker has completed the job.")

            elif isinstance(current_step, AgentStep):
                await job.update_status(JobStatus.WORKING, f"Running agent step '{pipeflow.current_step_id}'...")

                agent_job: Job = Job(
                    id=f"{job.id}_tool_{uuid.uuid4().hex[:6]}",
                    context_bindings=[
                        current_step.chat_history,
                    ],
                    resource_bindings=[
                        current_step.inference_provider,
                        current_step.agent_role,
                    ]
                )
                job.delegates.append(agent_job)

                await job.update_status(JobStatus.WORKING, "Starting agent worker...")
                await self.agent_worker.run(job=agent_job)
                await job.update_status(JobStatus.WORKING, "Agent worker has completed the job.")

            elif isinstance(current_step, DecisionStep):
                await job.update_status(JobStatus.WORKING, f"Running decision step '{pipeflow.current_step_id}'...")

                input_data = self.pull_context(current_step.input_data)
                if isinstance(input_data, BaseModel):
                    input_data = input_data.model_dump(mode="json")
        
                if not isinstance(input_data, dict):
                    raise PipelineWorkerError(f"Invalid data input type: '{type(input_data)}'")

                await job.update_status(JobStatus.WORKING, "Running decision code")
                out_queue: "multiprocessing.Queue" = _MP_CONTEXT.Queue()
                process = _MP_CONTEXT.Process(
                    target=_run_code,
                    args=(current_step.code, current_step.code_type, input_data, out_queue),
                    daemon=True,
                )
                process.start()
                process.join(_CODE_TIMEOUT)

                await job.update_status(JobStatus.WORKING, "Validating results")
                if process.is_alive():
                    process.terminate()
                    process.join()
                    raise PipelineWorkerError(f"Timed out after {_CODE_TIMEOUT}s")

                if out_queue.empty():
                    raise PipelineWorkerError(f"Process exited without a result (exit code {process.exitcode})",)

                status, result = out_queue.get()
                if status != "ok":
                    raise PipelineWorkerError(f"Process error reported: {result}")

                if result not in current_step.target_options:
                    raise PipelineWorkerError(f"Target step '{result}' is not a valid option")

                current_step.target_id = result

                await job.update_status(JobStatus.WORKING, f"Chosen target: {result}")

            pipeflow.step_history.append(pipeflow.current_step_id)
            pipeflow.current_step_id = current_step.target_id
            pipeflow.save()
