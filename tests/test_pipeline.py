import pytest

from datorum.exceptions import (
    InvalidIdentifierException,
)
from datorum.pipeline import (
    BasePipelineStep,
    HumanInteractionStep,
    PipeFlow,
    Pipeline,
    PipelineCollection,
)


@pytest.mark.depends(
    on=["tests/test_wiring.py", "tests/test_inference.py", "tests/test_context.py"]
)
def test_validators():
    pipeline: Pipeline = Pipeline.model_validate(
        {
            "id": "mocked-pipeline-1",
            "steps": [
                {
                    "type": "human",
                    "id": "step-1-human",
                    "message": "Agent waiting for approval.",
                }
            ],
        }
    )

    assert pipeline.steps[0].id == "step-1-human"
    assert pipeline.steps[0].pipeline is pipeline

    pipeflow = PipeFlow(pipeline=pipeline)
    assert pipeline.parent is pipeflow

    collection = PipelineCollection(pipelines=[pipeline])
    assert pipeline.parent is collection


@pytest.mark.depends(on=["test_validators"])
def test_errors():
    step = BasePipelineStep(type="unknown", id="mocked-step")
    with pytest.raises(ValueError, match="Pipeline not found"):
        assert step.pipeline

    pipeline = Pipeline(id="mocked-pipeline")
    with pytest.raises(ValueError, match=r"Pipeline '.*?' has no parent"):
        assert pipeline.parent

    step_clones_1 = HumanInteractionStep(id="step-clone", message="Cloned!!!")
    step_clones_2 = HumanInteractionStep(id="step-clone", message="Cloned!!!")

    with pytest.raises(InvalidIdentifierException):
        Pipeline(id="mocked-pipeline", steps=[step_clones_1, step_clones_2])

    pipeline_clones_1 = Pipeline(id="pipeline-clone")
    pipeline_clones_2 = Pipeline(id="pipeline-clone")

    with pytest.raises(InvalidIdentifierException):
        PipelineCollection(pipelines=[pipeline_clones_1, pipeline_clones_2])
