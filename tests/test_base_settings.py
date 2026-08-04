from pathlib import Path
from typing import Optional

import pytest
from pydantic import Field

from datorum.exceptions import ConfigException, NoFilePathException
from datorum.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class MockedModel(BaseDatorumSettings):
    another_model: Optional["MockedModel"] = None
    a_list: list["MockedModel"] = Field(default_factory=list)
    a_dict: dict[str, "MockedModel"] = Field(default_factory=dict)


class MockedPersistentModel(BaseDatorumPersistentSettings):
    a_file_path: Path
    a_text_content: str
    a_model: MockedModel | None = None
    a_persistent_model: Optional["MockedPersistentModel"] = None


def test_persistence(tmp_path: Path):
    workspace_path = tmp_path / "workspace"
    settings_path = workspace_path / "mocked.yml"

    file_name = "test.txt"
    file_path = workspace_path / file_name
    file_content = "Persistence ok!"
    text_content = "This goes inside the YAML file."

    workspace_path.mkdir(parents=True, exist_ok=True)
    file_path.write_text(file_content, encoding="utf-8")

    child_data1 = MockedModel()

    data1 = MockedPersistentModel(
        a_file_path=Path(file_name),
        a_text_content=text_content,
        a_model=child_data1,
    )
    data1.save_as(settings_path=settings_path)

    data2: MockedPersistentModel = MockedPersistentModel.load(
        settings_path=settings_path
    )

    assert data2.a_file_path == Path(file_name)
    assert data2.a_text_content == text_content
    assert data2.a_model.persistent.settings_path == settings_path

    file_content2 = (workspace_path / data2.a_file_path).read_text(encoding="utf-8")
    assert file_content == file_content2


def test_exceptions():
    child_data = MockedModel()
    with pytest.raises(ConfigException):
        assert child_data.persistent

    data = MockedPersistentModel(
        a_file_path=Path("test.yml"),
        a_text_content="test",
    )
    with pytest.raises(NoFilePathException):
        assert data.settings_path


@pytest.mark.depends(on=["test_persistence", "test_exceptions"])
def test_special_cases():
    data1 = MockedModel()
    data1.another_model = data1

    data2 = MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
        a_model=data1,
    )

    assert data2 is data1.another_model.persistent

    data1 = MockedModel()
    list1 = [data1]
    list1.append(list1)
    data1.a_list = list1

    data2 = MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
        a_model=data1,
    )

    assert data2 is data1.a_list[0].persistent

    data1 = MockedModel()
    dict1 = {"data1": data1}
    dict1["dict1"] = dict1
    data1.a_dict = dict1

    data2 = MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
        a_model=data1,
    )

    assert data2 is data1.a_dict["data1"].persistent

    data1 = MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
    )

    data2 = MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
        a_persistent_model=data1,
    )
