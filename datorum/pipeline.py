from collections import Counter
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import Field, PrivateAttr, model_validator

from .exceptions import InvalidIdentifierException
from .settings import BaseDatorumPersistentSettings, BaseDatorumSettings
from .wiring import InputPort, LivePort, OutputPort, ResourcePort


class BasePipelineStep(BaseDatorumSettings):
    type: str
    id: str
    target_id: str | None = None
    description: str | None = None

    _pipeline: Optional["Pipeline"] = PrivateAttr(default=None)

    @property
    def pipeline(self) -> "Pipeline":
        if self._pipeline is None:
            raise ValueError("Pipeline not found")
        return self._pipeline


class HumanInteractionStep(BasePipelineStep):
    type: Literal["human"] = "human"
    message: str

    dialog_port: LivePort = Field(default_factory=LivePort)
    reference_ports: dict[str, LivePort] = Field(default_factory=dict)


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
    chat_history_port: LivePort = Field(default_factory=LivePort)
    output_port: OutputPort = Field(default_factory=OutputPort)

    tools: list[str] = Field(default_factory=list)


class CodeType(str, Enum):
    FORMULA = "formula"
    SNIPPET = "snippet"


class DecisionStep(BasePipelineStep):
    type: Literal["decision"] = "decision"
    target_options: list[str] = Field(default_factory=list)
    code_type: CodeType = CodeType.FORMULA
    code: str = ""

    input_port: InputPort = Field(default_factory=InputPort)


class Pipeline(BaseDatorumSettings):
    id: str
    description: str | None = None

    steps: dict[str,
        Annotated[
            HumanInteractionStep | ToolStep | AgentStep | DecisionStep, Field(discriminator="type")
        ]
    ] = Field(default_factory=dict)

    _parent: Union["PipelineCollection", "PipeFlow"] | None = PrivateAttr(default=None)

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
    id: str
    planning = "planning"
    started = "started"
    paused = "paused"
    finished = "finished"
    crashed = "crashed"


class PipeFlow(BaseDatorumPersistentSettings):
    pipeline: Pipeline

    state: PipeFlowState = PipeFlowState.planning
    current_step: str | None = None
    step_history: list[str] = Field(default_factory=list)

    started_at: datetime | None = None
    last_updated_at: datetime | None = None
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
            duplicates = [
                id for id, count in Counter(pipeline_ids).items() if count > 1
            ]
            raise InvalidIdentifierException(
                f"Duplicate pipeline IDs found in pipeline collection: {duplicates}"
            )

        for pipeline in self.pipelines:
            pipeline.parent = self

        return self
