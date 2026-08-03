from collections import Counter
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Literal, Optional, Annotated, Union

from pydantic import Field, PrivateAttr, model_validator

from .settings_base import BaseDatorumSettings, BaseDatorumPersistentSettings
from .wiring import InputPort, OutputPort, LivePort, ResourcePort
from .agent import AIConfig, AgentRole, AIServiceProvider
from .document import DocumentContext
from .exceptions import InvalidIdentifierException


class ToolBoxSettings(BaseDatorumSettings):

    id: str
    toolbox: str
    settings: dict[str, any] = Field(default_factory=dict)


class BasePipelineStep(BaseDatorumSettings):

    type: str
    id: str
    description: str | None = None

    _pipeline: Optional['Pipeline'] = PrivateAttr(default=None)

    @property
    def pipeline(self) -> 'Pipeline':
        if self._pipeline is None:
            raise ValueError("Pipeline not found")
        return self._pipeline

    @property
    def work_dir(self) -> Path:
        return self.pipeline.pipeflow.work_dir


class HumanInteractionStep(BasePipelineStep):

    type: Literal["human"] = "human"
    message: str

    dialog_port: LivePort = Field(default_factory=LivePort)
    reference_ports: dict[str, LivePort] = Field(default_factory=dict)

    logger_port: ResourcePort = Field(default_factory=ResourcePort)


class ToolStep(BasePipelineStep):

    type: Literal["tool"] = "tool"

    toolbox_setup_id: str
    tool_name: str
    tool_params_port: InputPort = Field(default_factory=InputPort)
    tool_result_port: OutputPort = Field(default_factory=OutputPort)


class AgentStep(BasePipelineStep):

    type: Literal["agent"] = "agent"
    provider_id: str
    role_id: str

    system_instructions_port: InputPort = Field(default_factory=InputPort)
    user_prompt_port: InputPort = Field(default_factory=InputPort)
    output_port: InputPort = Field(default_factory=OutputPort)

    tools: list[str] = Field(default_factory=list)


class Pipeline(BaseDatorumSettings):

    id: str
    description: str | None = None

    steps: list[Annotated[
        Union[
            HumanInteractionStep,
            ToolStep,
            ModelStep,
            AgentStep,
        ], Field(discriminator="type")]
    ] = Field(default_factory=list)

    _collection: Optional["PipelineCollection"] = PrivateAttr(default=None)
    _pipeflow: Optional["PipeFlow"] = PrivateAttr(default=None)

    @property
    def collection(self) -> "PipelineCollection":
        if self._collection is None:
            raise ValueError("Pipeline collection not found")
        return self._collection

    @property
    def pipeflow(self) -> "PipeFlow":
        if self._pipeflow is None:
            raise ValueError("Pipeline is not in a flow")
        return self._pipeflow

    @model_validator(mode="after")
    def _post_init_setup(self) -> "Pipeline":
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            duplicates = [id for id, count in Counter(step_ids).items() if count > 1]
            raise InvalidIdentifierException(
                f"Duplicate step IDs found in '{self.id}': {duplicates}"
            )
        for step in self.steps:
            step._pipeline = self


class PipeFlowState(str, Enun):

    planning = "planning"
    started  = "started"
    paused   = "paused"
    finished = "finished"
    crashed  = "crashed"

class PipeFlow(BaseDatorumPersistentSettings):

    work_dir: Path
    pipeline: Pipeline

    state: PipeFlowState = PipeFlowState.planning
    current_step: int = -1

    started_at: datetime | None = None
    finished_at: datetime | None = None

    _collection: Optional['PipelineCollection'] = PrivateAttr(default=None)

    @property
    def collection(self) -> 'PipelineCollection':
        if self._collection is None:
            raise ValueError("Pipeline collection not found")
        return self._collection

    @model_validator(mode="after")
    def _post_init_setup(self) -> "PipeFlow":
        self.pipeline._pipeflow = self
        return self


class PipelineCollection(BaseDatorumPersistentSettings):

    pipelines: list[Pipeline] = Field(default_factory=list)
    flow_files: list[str] = Field(default_factory=list)
    toolboxes: list[ToolBoxSettings] = Field(default_factory=list)

    _config: AIConfig | None = PrivateAttr(default=None)
    _domains: DomainCollection | None = PrivateAttr(default=None)
    _pipeflows: list[PipeFlow] | None = PrivateAttr(default=None)

    @classmethod
    def load_pipelines(cls, config: AIConfig) -> PipelineCollection:
        instance: PipelineCollection = cls.load(
            config.settings_path / "plumbing.yml")
        instance._config = config
        instance._domains = DomainCollection.load(
            config.settings_path / "domains.yml")
        return instance

    @property
    def config(self) -> AIConfig:
        if self._config is None:
            raise ValueError("Config not found")
        return self._config

    @property
    def domains(self) -> DomainCollection:
        if self._domains is None:
            raise ValueError("Domains not found")
        return self._domains

    @property
    def pipeflows(self) -> list[PipeFlow]:
        if self._pipeflows is None:
            self._pipeflows = [
                PipeFlow.load(self.settings_path / flow_file)
                for flow_file in self.flow_files
            ]
        return self._pipeflows

    @model_validator(mode="after")
    def _post_init_setup(self) -> "PipelineCollection":
        pipeline_ids = [pipeline.id for pipeline in self.pipelines]
        if len(pipeline_ids) != len(set(pipeline_ids)):
            duplicates = [id for id, count in Counter(pipeline_ids).items() if count > 1]
            raise InvalidIdentifierException(
                f"Duplicate pipeline IDs found in '{self.id}': {duplicates}"
            )
        flow_ids = [flow.id for flow in self.flows]
        if len(flow_ids) != len(set(flow_ids)):
            duplicates = [id for id, count in Counter(flow_ids).items() if count > 1]
            raise InvalidIdentifierException(
                f"Duplicate pipe flow IDs found in '{self.id}': {duplicates}"
            )

        for pipeline in self.pipelines:
            pipeline._collection = self
        for flow in self.flows:
            flow._collection = self
