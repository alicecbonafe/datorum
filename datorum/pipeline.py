from collections import Counter
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Literal, Optional, Annotated, Union

from pydantic import Field, PrivateAttr, model_validator

from .settings_base import BaseDatorumSettings, BaseDatorumPersistentSettings
from .config import GeneralConfig, AgentRole, AIServiceProvider
from .domain import DomainCollection
from .exceptions import InvalidIdentifierException


class ToolBoxSettings(BaseDatorumSettings):

    id: str
    toolbox: str
    settings: dict[str, any] = Field(default_factory=dict)


class BasePipelineStep(BaseDatorumSettings):

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

    @property
    def work_dir(self) -> Path:
        return self.pipeline.pipeflow.work_dir


class HumanInteractionStep(BasePipelineStep):

    type: Literal["human"] = "human"
    message: str
    interface_file: str
    additional_files: dict[str, str] = Field(default_factory=dict)

    @property
    def interface_path(self) -> Path:
        return self.work_dir / self.interface_file

    def list_additional_files(self) -> list[str]:
        return self.additional_files.keys()

    def get_additional_path(self, file: str) -> Path:
        return self.work_dir / self.additional_files[file]


class ToolStep(BasePipelineStep):

    type: Literal["tool"] = "tool"

    toolbox: str
    toolbox_params: dict[str, any] = Field(default_factory=dict)
    toolbox_params_file: str | None = None

    tool: str
    tool_params: dict[str, any] = Field(default_factory=dict)
    tool_params_file: str | None = None

    @property
    def toolbox_params_path(self) -> Path | None:
        return self.work_dir / self.toolbox_params_file \
            if self.toolbox_params_file else None

    @property
    def tool_params_path(self) -> Path | None:
        return self.work_dir / self.tool_params_file \
            if self.tool_params_file else None

    def get_toolbox_params(self) -> dict[str, any]:
        _params = self.toolbox_params
        if self.toolbox_params_file and self.toolbox_params_path.exists():
            _params.update(json.loads(
                self.toolbox_params_path.read_text(encoding="utf-8")
            ))
        return _params

    def get_tool_params(self) -> dict[str, any]:
        _params = self.tool_params
        if self.tool_params_file and self.tool_params_path.exists():
            _params.update(json.loads(
                self.tool_params_path.read_text(encoding="utf-8")
            ))
        return _params


class AgentStep(BasePipelineStep):

    type: Literal["agent"] = "agent"
    provider_id: str
    role_id: str
    output_file: str
    system_instructions: str | None = None
    system_instructions_file: str | None = None
    user_prompt: str | None = None
    user_prompt_file: str | None = None
    tools: list[str] = Field(default_factory=list)

    @property
    def output_path(self) -> Path:
        return self.work_dir / self.output_file

    @property
    def system_instructions_path(self) -> Path | None:
        return self.work_dir / self.system_instructions_file \
            if self.system_instructions_file else None

    @property
    def user_prompt_path(self) -> Path | None:
        return self.work_dir / self.user_prompt_file \
            if self.user_prompt_file else None

    @property
    def role(self) -> AgentRole:
        return self.pipeline.collection.config.get_role(self.role_id)

    @property
    def provider(self) -> AIServiceProvider:
        return self.pipeline.collection.config.get_provider(self.provider_id)

    def get_system_instructions(self) -> str:
        _system_instruction: str

        if self.system_instructions_file and self.system_instructions_path.exists():
            _system_instruction = self.system_instructions_path.read_text(encoding="utf-8")
        elif self.system_instructions is not None:
            _system_instruction = self.system_instructions
        else:
            _system_instruction = self.role.system_instructions

        return _system_instruction

    def get_user_prompt(self) -> str:
        _user_prompt: str

        if self.user_prompt_file and self.user_prompt_path.exists():
            _user_prompt = self.user_prompt_path.read_text(encoding="utf-8")
        elif self.user_prompt is not None:
            _user_prompt = self.user_prompt
        else:
            _user_prompt = self.role.user_prompt

        return fallback


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

    _config: GeneralConfig | None = PrivateAttr(default=None)
    _domains: DomainCollection | None = PrivateAttr(default=None)
    _pipeflows: list[PipeFlow] | None = PrivateAttr(default=None)

    @classmethod
    def load_pipelines(cls, config: GeneralConfig) -> PipelineCollection:
        instance: PipelineCollection = cls.load(
            config.settings_path / "plumbing.yml")
        instance._config = config
        instance._domains = DomainCollection.load(
            config.settings_path / "domains.yml")
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
