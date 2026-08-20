import multiprocessing
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from RestrictedPython import (
    compile_restricted_eval,
    compile_restricted_exec,
    safe_globals,
)
from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
from RestrictedPython.Guards import (
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
    safer_getattr,
)

from ..agency.worker import AgentWorker
from ..binding.binder import Binder
from ..binding.settings import ContextBind, ContextBindType, ResourceBind
from ..tooling.worker import ToolWorker
from ..work.job import Job, JobStatus
from ..work.worker import Worker
from .exceptions import PipelineWorkerError
from .settings import (
    AgentStep,
    DecisionStep,
    HumanInteractionStep,
    PipeFlow,
    PipeFlowState,
    Pipeline,
    PlumbingKit,
    ToolStep,
)

_MP_CONTEXT = multiprocessing.get_context("spawn")
_CODE_TIMEOUT: float = 5.0
_RESULT_VAR: str = "target"


def _restricted_globals() -> dict[str, Any]:
    g: dict[str, Any] = dict(safe_globals)
    g["_getattr_"] = safer_getattr  # blocks `_private`/dunder access
    g["_getitem_"] = default_guarded_getitem  # input_data['field']
    g["_getiter_"] = default_guarded_getiter  # for/comprehension support
    g["_iter_unpack_sequence_"] = guarded_iter_unpack_sequence
    g["_unpack_sequence_"] = guarded_unpack_sequence
    return g


def _run_code(
    code: str,
    mode: Literal["formula", "snippet"],
    input_data: dict,
    out_queue: multiprocessing.Queue,
) -> None:
    try:
        glb = _restricted_globals()
        if mode == "formula":
            compiled = compile_restricted_eval(code, filename=f"<{_RESULT_VAR}>")
            if compiled.errors:
                raise SyntaxError("; ".join(compiled.errors))
            assert compiled.code
            result = eval(compiled.code, glb, {"input_data": input_data})
        else:
            compiled = compile_restricted_exec(code, filename=f"<{_RESULT_VAR}>")
            if compiled.errors:
                raise SyntaxError("; ".join(compiled.errors))
            assert compiled.code
            loc: dict[str, Any] = {"input_data": input_data}
            exec(compiled.code, glb, loc)  # noqa: S102
            if _RESULT_VAR not in loc:
                raise NameError(f"Snippet did not assign a value to '{_RESULT_VAR}'")
            result = loc[_RESULT_VAR]
        out_queue.put(("ok", result))
    except BaseException as exc:  # noqa: BLE001
        out_queue.put(("error", f"{type(exc).__name__}: {exc}"))


class PipelineWorker(Worker):
    def __init__(
        self,
        binder: Binder,
        plumbingkit: PlumbingKit,
        agent_worker: AgentWorker,
        tool_worker: ToolWorker,
    ):
        super().__init__(binder)
        self.plumbingkit: PlumbingKit = plumbingkit
        self.agent_worker: AgentWorker = agent_worker
        self.tool_worker: ToolWorker = tool_worker

        self._active_flows: dict[str, str] = {}  # flow_id -> job_id
        self._flow_cache: dict[str, PipeFlow] = {}

    def register_flow_factories(
        self, flow_path: Path, flow_id_template: str = "flow_{index}"
    ):
        flow_files: dict[str, Path] = {}
        last_index: int = -1

        prefix, suffix = flow_id_template.split("{index}")
        flow_file_re_str = re.escape(prefix) + r"(\d+)" + re.escape(f"{suffix}.yml")
        flow_file_re = re.compile(flow_file_re_str)

        flow_path.mkdir(parents=True, exist_ok=True)

        for candidate in flow_path.iterdir():
            if candidate.is_file():
                match = flow_file_re.fullmatch(candidate.name)
                if match:
                    index = int(match.group(1))
                    flow_id = flow_id_template.format(index=index)
                    flow_files[flow_id] = candidate
                    last_index = max(index, last_index)

        @self.binder.resource(name="create_pipeflow", force=True)
        def _create_pipeflow(pipeline_id) -> PipeFlow:
            nonlocal last_index

            if not pipeline_id:
                raise PipelineWorkerError("Pipeline ID is required")
            if pipeline_id not in self.plumbingkit.pipelines:
                raise PipelineWorkerError(f"Pipeline '{pipeline_id}' not found")
            pipeline: Pipeline = self.plumbingkit.pipelines[pipeline_id]

            index = last_index + 1
            flow_id = flow_id_template.format(index=index)
            flow_file = (flow_path / flow_id).with_suffix(".yml")

            while flow_file.exists():
                index += 1
                flow_id = flow_id_template.format(index=index)
                flow_file = (flow_path / flow_id).with_suffix(".yml")

            last_index = index
            flow_files[flow_id] = flow_file

            pipeline_copy: Pipeline = Pipeline.model_validate(
                pipeline.model_dump(mode="python")
            )
            pipeflow: PipeFlow = PipeFlow(
                id=flow_id,
                pipeline=pipeline_copy,
            )
            pipeflow.save_as(flow_file)
            self._flow_cache[flow_id] = pipeflow
            return pipeflow

        @self.binder.resource(name="restore_pipeflow", force=True)
        def _restore_pipeflow(flow_id) -> PipeFlow:
            if not flow_id:
                raise PipelineWorkerError("Pipeflow ID is required")

            if flow_id in self._flow_cache:
                return self._flow_cache[flow_id]

            if flow_id not in flow_files:
                flow_file = (flow_path / flow_id).with_suffix(".yml")
                if not flow_file.exists():
                    raise PipelineWorkerError(f"Pipeflow '{flow_id}' not found")
                flow_files[flow_id] = flow_file

            flow = PipeFlow.load(flow_files[flow_id])
            self._flow_cache[flow_id] = flow
            return flow

    def create_flow(self, pipeline_id: str):
        return self.binder.load_resource(
            ResourceBind(
                field_id="pipeflow",
                factory_name="create_pipeflow",
                selector=pipeline_id,
            )
        )

    async def work(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Creating/restoring pipeflow")

        pipeflow: PipeFlow
        pipeflow_bind: ResourceBind | None = next(
            (
                bind
                for bind in job.resource_bindings
                if bind.factory_name == "restore_pipeflow"
            ),
            None,
        )
        if pipeflow_bind:
            pipeflow = self.binder.load_resource(pipeflow_bind)
        else:
            pipeline_bind: ResourceBind | None = next(
                (
                    bind
                    for bind in job.resource_bindings
                    if bind.factory_name == "create_pipeflow"
                ),
                None,
            )
            if not pipeline_bind:
                raise PipelineWorkerError(
                    "Required binding not provided for 'create_pipeflow' or 'restore_pipeflow'"
                )
            pipeflow = self.binder.load_resource(pipeline_bind)

        if pipeflow.id in self._active_flows:
            raise PipelineWorkerError(
                f"Pipeflow '{pipeflow.id}' already running in job '{self._active_flows[pipeflow.id]}'"
            )
        self._active_flows[pipeflow.id] = job.id

        await job.update_status(JobStatus.WORKING, "Collecting pipeflow resources")

        if pipeflow.state == PipeFlowState.planning:
            await job.update_status(JobStatus.WORKING, "Initializing pipeflow")
            pipeflow.current_step_id = pipeflow.pipeline.first_step_id
            pipeflow.state = PipeFlowState.started
            pipeflow.save()
        else:
            await job.update_status(JobStatus.WORKING, "Recovering pipeflow")
            pipeflow.state = PipeFlowState.started
            pipeflow.save()

        try:
            while pipeflow.current_step_id is not None:
                if pipeflow.current_step_id not in pipeflow.pipeline.steps:
                    raise PipelineWorkerError(
                        f"Step '{pipeflow.current_step_id}' not found in Pipeline '{pipeflow.pipeline.id}'"
                    )

                current_step = pipeflow.pipeline.steps[pipeflow.current_step_id]
                if isinstance(current_step, HumanInteractionStep):
                    existing_interactive = next(
                        (
                            b
                            for b in job.context_bindings
                            if b.field_id == "interactive"
                        ),
                        None,
                    )
                    if existing_interactive:
                        existing_interactive.binded_id = (
                            current_step.interactive_document_id
                        )
                        existing_interactive.context = (
                            current_step.interactive_document_context
                        )
                        existing_interactive.context_bind_type = ContextBindType.model
                    else:
                        job.context_bindings.append(
                            ContextBind(
                                field_id="interactive",
                                binded_id=current_step.interactive_document_id,
                                context=current_step.interactive_document_context,
                                context_bind_type=ContextBindType.model,
                            )
                        )
                    pipeflow.state = PipeFlowState.paused
                    pipeflow.save()
                    await job.update_status(
                        JobStatus.PAUSING, "Waiting for human interaction."
                    )
                    await job.update_status(JobStatus.WORKING, "Resuming pipeflow...")

                elif isinstance(current_step, ToolStep):
                    await job.update_status(
                        JobStatus.WORKING,
                        f"Running tool step '{pipeflow.current_step_id}'...",
                    )

                    tool_job: Job = Job(
                        id=f"{job.id}_tool_{uuid.uuid4().hex[:6]}",
                        context_bindings=[
                            current_step.tool_params,
                            current_step.tool_result,
                            *current_step.custom_context,
                        ],
                        resource_bindings=[
                            current_step.toolbox_setup,
                            *current_step.custom_resources,
                        ],
                    )
                    job.delegates.append(tool_job)

                    await job.update_status(
                        JobStatus.WORKING,
                        f"Calling tool '{current_step.toolbox_setup.selector}'",
                    )
                    await self.tool_worker.run(tool_job)
                    await job.update_status(
                        JobStatus.WORKING, "Tool worker has completed the job."
                    )

                elif isinstance(current_step, AgentStep):
                    await job.update_status(
                        JobStatus.WORKING,
                        f"Running agent step '{pipeflow.current_step_id}'...",
                    )

                    agent_job: Job = Job(
                        id=f"{job.id}_tool_{uuid.uuid4().hex[:6]}",
                        context_bindings=[
                            current_step.chat_history,
                        ],
                        resource_bindings=[
                            current_step.inference_provider,
                            current_step.agent_role,
                        ],
                    )
                    job.delegates.append(agent_job)

                    await job.update_status(
                        JobStatus.WORKING, "Starting agent worker..."
                    )
                    await self.agent_worker.run(job=agent_job)
                    await job.update_status(
                        JobStatus.WORKING, "Agent worker has completed the job."
                    )

                elif isinstance(current_step, DecisionStep):
                    await job.update_status(
                        JobStatus.WORKING,
                        f"Running decision step '{pipeflow.current_step_id}'...",
                    )

                    input_data = self.binder.pull_context(current_step.input_data)
                    if isinstance(input_data, BaseModel):
                        input_data = input_data.model_dump(mode="json")

                    if not isinstance(input_data, dict):
                        raise PipelineWorkerError(
                            f"Invalid data input type: '{type(input_data)}'"
                        )

                    await job.update_status(JobStatus.WORKING, "Running decision code")
                    out_queue: multiprocessing.Queue = _MP_CONTEXT.Queue()
                    process = _MP_CONTEXT.Process(
                        target=_run_code,
                        args=(
                            current_step.code,
                            current_step.code_type,
                            input_data,
                            out_queue,
                        ),
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
                        raise PipelineWorkerError(
                            f"Process exited without a result (exit code {process.exitcode})",
                        )

                    status, result = out_queue.get()
                    if status != "ok":
                        raise PipelineWorkerError(f"Process error reported: {result}")

                    if result not in current_step.target_options:
                        raise PipelineWorkerError(
                            f"Target step '{result}' is not a valid option"
                        )

                    current_step.target_id = result

                    await job.update_status(
                        JobStatus.WORKING, f"Chosen target: {result}"
                    )

                pipeflow.step_history.append(pipeflow.current_step_id)
                pipeflow.current_step_id = current_step.target_id
                pipeflow.save()

            pipeflow.state = PipeFlowState.finished

        except Exception:
            pipeflow.state = PipeFlowState.finished
            raise

        finally:
            pipeflow.save()
            self._active_flows.pop(pipeflow.id, None)
