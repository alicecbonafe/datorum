from datetime import datetime
from typing import Optional

from ..context import DocumentReference
from ..exceptions import PipelineWorkerException
from ..inference import AIServiceProvider, AgentRole
from ..pipeline import (
    PipeFlow,
    PipeFlowState,
    HumanInteractionStep,
    ToolStep,
    AgentStep,
    DecisionStep,
)
from ..tooling import ToolBoxSetUp
from ..wiring import BasePort, DocumentBind
from .base import Worker, Job, JobStatus
from .agents import AgentWorker
from .tools import ToolWorker


class PipelineWorker(Worker):

    def __init__(
        self,
        pipeflow: PipeFlow,
        providers: dict[str, AIServiceProvider],
        provider_api_keys: dict[str, str],
        roles: dict[str, AgentRole],
        toolkit: list[ToolBoxSetUp],
    ):
        super().__init__()
        self.pipeflow = pipeflow
        self.providers = providers
        self.provider_api_keys = provider_api_keys
        self.roles = roles
        self.toolkit = toolkit

    async def _get_document(self, job: Job, port: BasePort) -> Optional[DocumentReference]:
        if port.bind is None:
            return None
        if not isinstance(port.bind, DocumentBind):
            raise PipelineWorkerException("Port is not binded to a document")
        doc_id = port.bind.document_id
        return job.context.documents.get(doc_id)

    async def save_flow(
        self, *,
        state: Optional[PipeFlowState] = None,
        step_id: Optional[str] = None
    ):
        self.pipeflow.state = state or self.pipeflow.state
        now = datetime.now().astimezone()
        if state != PipeFlowState.planning and self.pipeflow.started_at is None:
            self.pipeflow.started_at = now
        self.pipeflow.last_updated_at = now
        if state in [PipeFlowState.finished, PipeFlowState.crashed] and self.pipeflow.finished_at is None:
            self.pipeflow.finished_at = now
        self.pipeflow.save()

    async def work(self, job: Job):
        current_step_id: str | None = self.pipeflow.current_step_id

        if current_step_id is None and self.pipeflow.started_at is None:
            current_step_id = self.pipeflow.pipeline.first_step_id
            self.pipeflow.current_step_id = current_step_id
            await self.save_flow(state=PipeFlowState.started)

        while current_step_id is not None:
            if current_step_id not in self.pipeflow.pipeline.steps:
                raise PipelineWorkerException(f"Step '{current_step_id}' not found in Pipeline '{self.pipeflow.pipeline.id}'")

            current_step = self.pipeflow.pipeline.steps[current_step_id]
            if current_step.type == "human":
                assert isinstance(current_step, HumanInteractionStep)
                await job.update_status(JobStatus.PAUSING, "Waiting for human interaction.")
                await job.update_status(JobStatus.WORKING, "Resuming pipeline...")
            elif current_step.type == "tool":
                assert isinstance(current_step, ToolStep)
                await job.update_status(JobStatus.WORKING, f"Running tool step '{current_step_id}'...")

                tool_params_doc = self._get_document(
                    job=job, port=current_step.tool_params_port)
                tool_result_doc = self._get_document(
                    job=job, port=current_step.tool_result_port)

                documents = {**job.context.documents}
                if tool_params_doc is not None:
                    documents["tool_params"] = tool_params_doc
                if tool_result_doc is not None:
                    documents["tool_result"] = tool_result_doc
                tool_job = self.create_delegated_job(
                    origin=job, include_docs=documents)

                toolbox = next((
                    toolbox for toolbox in self.toolkit \
                        if toolbox.id == current_step.toolbox_setup_id
                ), None)
                if toolbox is None:
                    raise PipelineWorkerException(f"Toolbox '{current_step.toolbox_setup_id}' not found")
                tool_worker = ToolWorker(
                    toolbox=toolbox,
                    tool_name=current_step.tool_name,
                )

                await job.update_status(JobStatus.WORKING, "Starting tool worker...")
                await tool_worker.run(job=tool_job)
                await job.update_status(JobStatus.WORKING, "Tool worker has completed the job.")

            elif current_step.type == "agent":
                assert isinstance(current_step, AgentStep)
                await job.update_status(JobStatus.WORKING, f"Running agent step '{current_step_id}'...")

                system_instructions_doc = self._get_document(
                    job=job, port=current_step.system_instructions_port)
                user_prompt_doc = self._get_document(
                    job=job, port=current_step.user_prompt_port)
                chat_history_doc = self._get_document(
                    job=job, port=current_step.chat_history_port)
                output_doc = self._get_document(
                    job=job, port=current_step.output_port)

                documents = {**job.context.documents}
                if system_instructions_doc is not None:
                    documents["system_instructions"] = system_instructions_doc
                if user_prompt_doc is not None:
                    documents["user_prompt"] = user_prompt_doc
                if chat_history_doc is not None:
                    documents["chat_history"] = chat_history_doc
                if output_doc is not None:
                    documents["output"] = output_doc
                agent_job = self.create_delegated_job(
                    origin=job, include_docs=documents)

                agent_toolkit: list[ToolBoxSetUp] = []
                for toolbox_setup in self.toolkit:
                    toolbox_setup_new: Optional[ToolBoxSetUp] = None
                    for tool in toolbox_setup.tools_enabled:
                        tool_id = f"{toolbox_setup.id}.{tool}"
                        if tool_id in current_step.tools:
                            if toolbox_setup_new is None:
                                toolbox_setup_new = ToolBoxSetUp(
                                    id=f"{toolbox_setup.id}-subset-{uuid.uuid4().hex[:6]}",
                                    toolbox_name=toolbox_setup.toolbox_name,
                                    custom_ports=toolbox_setup.custom_ports
                                )
                            toolbox_setup_new.tools_enabled.append(tool)
                    if toolbox_setup_new is not None:
                        agent_toolkit.append(toolbox_setup_new)

                agent_worker = AgentWorker(
                    provider=self.providers[current_step.provider_id],
                    role=self.roles[current_step.role_id],
                    api_key=self.provider_api_keys[current_step.provider_id],
                    toolkit=agent_toolkit,
                )

                await job.update_status(JobStatus.WORKING, "Starting agent worker...")
                await agent_worker.run(job=agent_job)
                await job.update_status(JobStatus.WORKING, "Agent worker has completed the job.")

            elif current_step.type == "decision":
                assert isinstance(current_step, DecisionStep)
                # TODO

            self.pipeflow.step_history.append(current_step_id)
            current_step_id = current_step.target_id
            self.pipeflow.current_step_id = current_step_id
            await self.save_flow()
