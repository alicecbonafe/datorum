from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from datorum.binding.settings import ContextBind, ContextBindType, ResourceBind
from datorum.plumbing.settings import (
    AgentStep,
    BasePipelineStep,
    DecisionStep,
    HumanInteractionStep,
    PipeFlow,
    PipeFlowState,
    Pipeline,
    PlumbingKit,
    ToolStep,
)


# ==============================================================================
# Helpers
# ==============================================================================

def _chat_bind(field_id: str = "chat_history", binded_id: str = "chat_doc") -> ContextBind:
    return ContextBind(field_id=field_id, binded_id=binded_id)


def _resource_bind(field_id: str, factory_name: str, selector: str | None = None) -> ResourceBind:
    return ResourceBind(field_id=field_id, factory_name=factory_name, selector=selector)


# ==============================================================================
# BasePipelineStep / step subclasses
# ==============================================================================

def test_human_interaction_step_defaults():
    step = HumanInteractionStep(
        id="s1",
        interactive=ContextBind(
            field_id="interactive",
            binded_id="chat_doc",
        ),
    )
    assert step.type == "human"
    assert step.target_id is None
    assert step.description is None


def test_tool_step_defaults():
    step = ToolStep(
        id="s1",
        tool_params=_chat_bind("tool_params", "doc1"),
        tool_result=_chat_bind("tool_result", "doc1"),
        toolbox_setup=_resource_bind("toolbox_setup", "toolbox_setup", "box1.tool1"),
    )
    assert step.type == "tool"
    assert step.custom_context == []
    assert step.custom_resources == []


def test_agent_step_defaults():
    step = AgentStep(
        id="s1",
        chat_history=_chat_bind(),
        inference_provider=_resource_bind("inference_provider", "inference_provider", "p1"),
        agent_role=_resource_bind("agent_role", "agent_role", "r1"),
    )
    assert step.type == "agent"


def test_decision_step_defaults():
    step = DecisionStep(id="s1", input_data=_chat_bind("input_data", "doc1"))
    assert step.type == "decision"
    assert step.code_type == "formula"
    assert step.code == ""
    assert step.target_options == []


# ==============================================================================
# Pipeline (discriminated union of steps)
# ==============================================================================

def test_pipeline_defaults_and_discriminated_union_from_dicts():
    pipeline = Pipeline.model_validate({
        "id": "pipe1",
        "steps": {
            "in": {
                "type": "human",
                "id": "in",
                "interactive": {
                    "field_id": "interactive",
                    "binded_id": "doc1",
                    "context": None,
                    "context_bind_type": "model",
                    "local": False,
                }
            },
            "decide": {
                "type": "decision",
                "id": "decide",
                "input_data": {"field_id": "input_data", "binded_id": "doc1"},
            },
        },
    })

    assert pipeline.first_step_id == "in"
    assert isinstance(pipeline.steps["in"], HumanInteractionStep)
    assert isinstance(pipeline.steps["decide"], DecisionStep)


def test_pipeline_discriminated_union_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Pipeline.model_validate({
            "id": "pipe1",
            "steps": {
                "bad": {"type": "not-a-real-type", "id": "bad"},
            },
        })


def test_pipeline_empty_steps_default():
    pipeline = Pipeline(id="pipe1")
    assert pipeline.steps == {}
    assert pipeline.first_step_id == "in"


# ==============================================================================
# PipeFlowState
# ==============================================================================

def test_pipe_flow_state_values():
    assert PipeFlowState.planning == "planning"
    assert PipeFlowState.started == "started"
    assert PipeFlowState.paused == "paused"
    assert PipeFlowState.finished == "finished"
    assert PipeFlowState.crashed == "crashed"


# ==============================================================================
# PipeFlow.save()
# ==============================================================================

def test_pipe_flow_save_sets_started_at_on_first_non_planning_save(tmp_path: Path):
    pipeline = Pipeline(id="pipe1")
    flow = PipeFlow(id="flow1", pipeline=pipeline, state=PipeFlowState.started)
    flow.save_as(tmp_path / "flow1.yml")

    assert flow.started_at is not None
    assert flow.last_updated_at is not None
    assert flow.finished_at is None
    assert (tmp_path / "flow1.yml").exists()


def test_pipe_flow_save_does_not_overwrite_existing_started_at(tmp_path: Path):
    pipeline = Pipeline(id="pipe1")
    flow = PipeFlow(id="flow1", pipeline=pipeline, state=PipeFlowState.started)
    flow.save_as(tmp_path / "flow1.yml")
    first_started_at = flow.started_at

    flow.save()
    assert flow.started_at == first_started_at


def test_pipe_flow_save_in_planning_state_leaves_started_at_none(tmp_path: Path):
    pipeline = Pipeline(id="pipe1")
    flow = PipeFlow(id="flow1", pipeline=pipeline)  # default state: planning
    flow.save_as(tmp_path / "flow1.yml")

    assert flow.state == PipeFlowState.planning
    assert flow.started_at is None
    assert flow.last_updated_at is not None


def test_pipe_flow_save_sets_finished_at_when_finished(tmp_path: Path):
    pipeline = Pipeline(id="pipe1")
    flow = PipeFlow(id="flow1", pipeline=pipeline, state=PipeFlowState.finished)
    flow.save_as(tmp_path / "flow1.yml")

    assert flow.finished_at is not None
    assert flow.started_at is not None


def test_pipe_flow_save_sets_finished_at_when_crashed(tmp_path: Path):
    pipeline = Pipeline(id="pipe1")
    flow = PipeFlow(id="flow1", pipeline=pipeline, state=PipeFlowState.crashed)
    flow.save_as(tmp_path / "flow1.yml")

    assert flow.finished_at is not None


def test_pipe_flow_save_does_not_overwrite_existing_finished_at(tmp_path: Path):
    pipeline = Pipeline(id="pipe1")
    flow = PipeFlow(id="flow1", pipeline=pipeline, state=PipeFlowState.finished)
    flow.save_as(tmp_path / "flow1.yml")
    first_finished_at = flow.finished_at

    flow.save()
    assert flow.finished_at == first_finished_at


def test_pipe_flow_roundtrip_load(tmp_path: Path):
    step = HumanInteractionStep(
        id="in",
        interactive=ContextBind(
            field_id="interactive",
            binded_id="chat_history",
        ),
        target_id=None,
    )
    pipeline = Pipeline(id="pipe1", steps={"in": step}, first_step_id="in")
    flow = PipeFlow(id="flow1", pipeline=pipeline, state=PipeFlowState.started, current_step_id="in")
    flow.save_as(tmp_path / "flow1.yml")

    loaded = PipeFlow.load(tmp_path / "flow1.yml")
    assert loaded.id == "flow1"
    assert loaded.current_step_id == "in"
    assert isinstance(loaded.pipeline.steps["in"], HumanInteractionStep)


# ==============================================================================
# PlumbingKit
# ==============================================================================

def test_plumbingkit_defaults():
    kit = PlumbingKit()
    assert kit.pipelines == {}


def test_plumbingkit_holds_pipelines():
    pipeline = Pipeline(id="pipe1")
    kit = PlumbingKit(pipelines={"pipe1": pipeline})
    assert kit.pipelines["pipe1"] is pipeline