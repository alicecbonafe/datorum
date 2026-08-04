from collections import Counter
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Literal, Optional, Annotated, Union

from pydantic import Field, PrivateAttr, model_validator

from .settings import BaseDatorumSettings, BaseDatorumPersistentSettings
from .wiring import InputPort, OutputPort, LivePort, ResourcePort
from .inference import AIConfig, AgentRole, AIServiceProvider
from .context import DocumentContext
from .exceptions import InvalidIdentifierException


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
            AgentStep,
        ], Field(discriminator="type")]
    ] = Field(default_factory=list)

    _parent: Optional[Union[
        "PipelineCollection", "PipeFlow"
    ]] = PrivateAttr(default=None)

    @property
    def parent(self) -> Union["PipelineCollection", "PipeFlow"]:
        if self._parent is None:
            raise ValueError(f"Pipeline '{id}' has no parent")
        return self._parent

    @parent.setter
    def parent(self, value: Union["PipelineCollection", "PipeFlow"]):
        self._parent = value

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
        return self


class PipeFlowState(str, Enum):

    planning = "planning"
    started  = "started"
    paused   = "paused"
    finished = "finished"
    crashed  = "crashed"

class PipeFlow(BaseDatorumPersistentSettings):

    pipeline: Pipeline

    state: PipeFlowState = PipeFlowState.planning
    current_step: int = -1

    started_at: datetime | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def _post_init_setup(self) -> "PipeFlow":
        self.pipeline.parent = self
        return self


class PipelineCollection(BaseDatorumPersistentSettings):

    pipelines: list[Pipeline] = Field(default_factory=list)

    @model_validator(mode="after")
    def _post_init_setup(self) -> "PipelineCollection":
        pipeline_ids = [pipeline.id for pipeline in self.pipelines]
        if len(pipeline_ids) != len(set(pipeline_ids)):
            duplicates = [id for id, count in Counter(pipeline_ids).items() if count > 1]
            raise InvalidIdentifierException(
                f"Duplicate pipeline IDs found in pipeline collection: {duplicates}"
            )

        for pipeline in self.pipelines:
            pipeline.parent = self

        return self
