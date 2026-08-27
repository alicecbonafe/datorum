from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field

from ..binding.settings import ContextBind, ResourceBind
from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class BasePipelineStep(BaseDatorumSettings):
    """Base class for step definitions in a pipeline."""

    type: str = Field(description="Step type discriminator.")
    id: str = Field(description="Step identifier, unique within its pipeline.")
    target_id: str | None = Field(
        default=None,
        description="ID of the next step to run after this one.",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description of the step.",
    )


class HumanInteractionStep(BasePipelineStep):
    """Pipeline step pausing execution for user input or file edits."""

    type: Literal["human"] = Field(
        default="human",
        description="Step discriminator, always 'human'.",
    )

    interactive: ContextBind = Field(description="Context binding supplying the document the user is asked to edit.")

    # DEPRECATED:
    # interactive_document_id: str = Field(description="ID of the document the user is asked to edit.")
    # interactive_document_context: str | list[str] | None = Field(
    #     default=None,
    #     description="Context ID filter for the interactive document.",
    # )


class ToolStep(BasePipelineStep):
    """Pipeline step executing a tool."""

    type: Literal["tool"] = Field(
        default="tool",
        description="Step discriminator, always 'tool'.",
    )

    tool_params: ContextBind = Field(description="Context binding supplying the tool's parameters.")
    tool_result: ContextBind = Field(description="Context binding the tool's result is written to.")
    toolbox_setup: ResourceBind = Field(description="Resource binding selecting the toolbox setup and tool to run.")

    custom_context: list[ContextBind] = Field(
        default_factory=list,
        description="Additional context bindings for the toolbox's own fields.",
    )
    custom_resources: list[ResourceBind] = Field(
        default_factory=list,
        description="Additional resource bindings for the toolbox's own fields.",
    )


class AgentStep(BasePipelineStep):
    """Pipeline step executing an agent turn."""

    type: Literal["agent"] = Field(
        default="agent",
        description="Step discriminator, always 'agent'.",
    )

    chat_history: ContextBind = Field(description="Context binding for the agent turn's chat history.")
    inference_provider: ResourceBind = Field(description="Resource binding selecting the inference provider.")
    agent_role: ResourceBind = Field(description="Resource binding selecting the agent role.")


class DecisionStep(BasePipelineStep):
    """Pipeline step performing dynamic path branching decisions."""

    type: Literal["decision"] = Field(
        default="decision",
        description="Step discriminator, always 'decision'.",
    )

    target_options: list[str] = Field(
        default_factory=list,
        description="Valid target step IDs the decision code may return.",
    )
    code_type: Literal["formula", "snippet"] = Field(
        default="formula",
        description="Whether `code` is evaluated with `eval` ('formula') or executed with `exec` ('snippet').",
    )
    code: str = Field(
        default="",
        description="Restricted Python code determining the next `target_id`.",
    )

    input_data: ContextBind = Field(description="Context binding supplying the data the decision code runs against.")


class Pipeline(BaseDatorumSettings):
    """Workflow pipeline containing ordered execution steps.

    A pipeline centralizes the settings for an entire chain of steps via the `target_id`
    field of each step, which serves as the reference for the next step. When the step
    is a `DecisionStep`, the target ID is dynamically modified based on a document from
    the context.
    """

    id: str = Field(description="Pipeline identifier.")
    description: str | None = Field(
        default=None,
        description="Human-readable description of the pipeline.",
    )

    steps: dict[
        str,
        Annotated[
            HumanInteractionStep | ToolStep | AgentStep | DecisionStep,
            Field(discriminator="type"),
        ],
    ] = Field(
        default_factory=dict,
        description="Pipeline steps, keyed by step ID.",
    )
    first_step_id: str = Field(
        default="in",
        description="ID of the step a new flow starts at.",
    )


class PipeFlowState(str, Enum):
    """Execution state tracking current pipeline step position and context values."""

    planning = "planning"
    started = "started"
    paused = "paused"
    finished = "finished"
    crashed = "crashed"


class PipeFlow(BaseDatorumPersistentSettings):
    """Persistent runtime state instance of a pipeline flow.

    This class represents a pipeline flow, including its current state, enabling it to
    be resumed, much like a checkpointing mechanism.

    The pipe flow also maintains a copy of the original pipeline. This allows for manual
    modification of a pipeline that has already started, without affecting the original.
    """

    id: str = Field(description="Flow instance identifier.")
    pipeline: Pipeline = Field(description="Working copy of the pipeline this flow is executing.")

    state: PipeFlowState = Field(
        default=PipeFlowState.planning,
        description="Current lifecycle state of the flow.",
    )
    current_step_id: str | None = Field(
        default=None,
        description="ID of the step currently executing or last executed.",
    )
    step_history: list[str] = Field(
        default_factory=list,
        description="IDs of steps executed so far, in order.",
    )

    started_at: datetime | None = Field(
        default=None,
        description="Timestamp the flow left the 'planning' state.",
    )
    last_updated_at: datetime | None = Field(
        default=None,
        description="Timestamp of the flow's last save.",
    )
    finished_at: datetime | None = Field(
        default=None,
        description="Timestamp the flow reached 'finished' or 'crashed'.",
    )

    def save(self):
        """Persist the flow, stamping `started_at`/`last_updated_at`/`finished_at` as appropriate.

        Overrides `BaseDatorumPersistentSettings.save` to keep the flow's timestamps in
        sync with its `state` before delegating to the base implementation.
        """

        now = datetime.now().astimezone()
        if self.state != PipeFlowState.planning and self.started_at is None:
            self.started_at = now
        self.last_updated_at = now
        if (
            self.state in [PipeFlowState.finished, PipeFlowState.crashed]
            and self.finished_at is None
        ):
            self.finished_at = now
        super().save()


class PlumbingKit(BaseDatorumPersistentSettings):
    """Persistent configuration structure managing registered pipeline workflows.

    In practice, pipelines in this class serve as templates for use in `PipeFlow`.
    """

    pipelines: dict[str, Pipeline] = Field(
        default_factory=dict,
        description="Registered pipeline templates, keyed by pipeline ID.",
    )
