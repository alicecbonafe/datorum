from collections import Counter
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import Field, PrivateAttr, model_validator

from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings
from ..context.settings import ResourceBind, ContextBind


class BasePipelineStep(BaseDatorumSettings):
    type: str
    id: str
    target_id: str | None = None
    description: str | None = None


class HumanInteractionStep(BasePipelineStep):
    type: Literal["human"] = "human"

    chat_history: ContextBind


class ToolStep(BasePipelineStep):
    type: Literal["tool"] = "tool"

    tool_params: ContextBind
    tool_result: ContextBind
    toolbox_setup: ResourceBind

    custom_context: list[ContextBind] = Field(default_factory=list)
    custom_resources: list[ResourceBind] = Field(default_factory=list)


class AgentStep(BasePipelineStep):
    type: Literal["agent"] = "agent"

    chat_history: ContextBind
    inference_provider: ResourceBind
    agent_role: ResourceBind


class DecisionStep(BasePipelineStep):
    type: Literal["decision"] = "decision"

    target_options: list[str] = Field(default_factory=list)
    code_type: Literal["formula", "snippet"] = "formula"
    code: str = ""

    input_data: ContextBind


class Pipeline(BaseDatorumSettings):
    id: str
    description: str | None = None

    steps: dict[str,
        Annotated[
            HumanInteractionStep | ToolStep | AgentStep | DecisionStep, Field(discriminator="type")
        ]
    ] = Field(default_factory=dict)
    first_step_id: str = "in"


class PipeFlowState(str, Enum):
    planning = "planning"
    started = "started"
    paused = "paused"
    finished = "finished"
    crashed = "crashed"


class PipeFlow(BaseDatorumPersistentSettings):
    id: str
    pipeline: Pipeline

    state: PipeFlowState = PipeFlowState.planning
    current_step_id: str | None = None
    step_history: list[str] = Field(default_factory=list)

    started_at: datetime | None = None
    last_updated_at: datetime | None = None
    finished_at: datetime | None = None

    def save(self):
        now = datetime.now().astimezone()
        if self.state != PipeFlowState.planning and self.started_at is None:
            self.started_at = now
        self.last_updated_at = now
        if self.state in [PipeFlowState.finished, PipeFlowState.crashed] and self.finished_at is None:
            self.finished_at = now
        super().save()


class PlumbingKit(BaseDatorumPersistentSettings):
    pipelines: dict[str, Pipeline] = Field(default_factory=dict)
