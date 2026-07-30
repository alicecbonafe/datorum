from collections import Counter
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Optional, Annotated, Union

from pydantic import Field, PrivateAttr, model_validator

from .base import BaseDatorumModel, BaseDatorumPersistentModel
from .config import GeneralConfig
from .domains import DomainCollection
from ..exceptions import InvalidIdentifierException

class BasePipelineStep(BaseDatorumModel):

    type: str
    id: str
    description: str | None = None
    domains: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    _pipeline: Optional['Pipeline'] = PrivateAttr(default=None)

    @property
    def pipeline(self) -> 'Pipeline':
        if self._pipeline is None:
            raise ValueError("Pipeline not found")
        return self._pipeline


class HumanInteractionStep(BasePipelineStep):

    type: Literal["human"] = "human"
    message: str


class ToolStep(BasePipelineStep):

    type: Literal["tool"] = "tool"
    tool: str
    params: list[dict[str, str]] = Field(default_factory=list)


class ModelStep(BasePipelineStep):

    type: Literal["model"] = "model"
    provider_id: str | None = None
    role_id: str | None = None


class AgentStep(ModelBasedStep):

    type: Literal["agent"] = "agent"
    agent_name: str
    instructions_template_file: Path | None = None
    tools: list[str] = Field(default_factory=list)


class Pipeline(BaseDatorumModel):

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

    @property
    def collection(self) -> "PipelineCollection":
        if self._collection is None:
            raise ValueError("Pipeline collection not found")
        return self._collection

    @model_validator
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

class PipeFlow(BaseDatorumPersistentModel):

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


class PipelineCollection(BaseDatorumPersistentModel):

    pipelines: list[Pipeline] = Field(default_factory=list)
    flows: list[PipeFlow] = Field(default_factory=list)

    _config: GeneralConfig | None = PrivateAttr(default=None)
    _domains: DomainCollection | None = PrivateAttr(default=None)

    @classmethod
    def load_pipelines(cls, config: GeneralConfig) -> PipelineCollection:
        instance: PipelineCollection = cls.load(
            config.data_dir / "plumbing.yml")
        instance._config = config
        instance._domains = DomainCollection.load(
            config.data_dir / "domains.yml")
        return instance

    @property
    def config(self) -> GeneralConfig:
        if self._config is None:
            raise ValueError("Config not found")
        return self._config

    @property
    def domains(self) -> DomainCollection:
        if self._domains is None:
            raise ValueError("Domains not found")
        return self._domains

    @model_validator
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
