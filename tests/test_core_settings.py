from pathlib import Path
from typing import Optional

import pytest
from pydantic import Field

from datorum.core.exceptions import SettingsError
from datorum.core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


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
    text_content_changed = "File content has changed."

    workspace_path.mkdir(parents=True, exist_ok=True)
    file_path.write_text(file_content, encoding="utf-8")

    child_data1 = MockedModel()
    child_data2 = MockedPersistentModel(
        a_file_path=Path(file_name),
        a_text_content=text_content
    )

    data1 = MockedPersistentModel(
        a_file_path=Path(file_name),
        a_text_content=text_content,
        a_model=child_data1,
        a_persistent_model=child_data2,
    )
    data1.save_as(settings_path=settings_path)

    data2: MockedPersistentModel = MockedPersistentModel.load(
        settings_path=settings_path
    )

    assert data2.a_file_path == Path(file_name)
    assert data2.a_text_content == text_content
    assert data2.a_model is not None
    assert data2.settings_path == settings_path
    assert data2.a_model.settings_path == settings_path
    assert data2.a_persistent_model.settings_path == settings_path

    file_content2 = (workspace_path / data2.a_file_path).read_text(encoding="utf-8")
    assert file_content == file_content2

    data2.a_text_content = text_content_changed
    data2.save()
    data1.reload()

    assert data1.a_text_content == text_content_changed


def test_exceptions():
    child_data = MockedModel()
    with pytest.raises(SettingsError):
        assert child_data.persistent

    data = MockedPersistentModel(
        a_file_path=Path("test.yml"),
        a_text_content="test",
    )
    with pytest.raises(SettingsError):
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
    list1.append(list1)  # type: ignore[arg-type]
    data1.a_list = list1

    data2 = MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
        a_model=data1,
    )

    assert data2 is data1.a_list[0].persistent

    data1 = MockedModel()
    dict1 = {"data1": data1}
    dict1["dict1"] = dict1  # type: ignore[assignment]
    data1.a_dict = dict1

    data2 = MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
        a_model=data1,
    )

    assert data2 is data1.a_dict["data1"].persistent

    MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
    )

    MockedPersistentModel(
        a_file_path=Path("test.txt"),
        a_text_content="text_content",
        a_persistent_model=data2,
    )


def test_nested_persistent_model_save_and_reload_delegate_to_root(tmp_path: Path):
    """save() and reload() called on a nested (non-root) persistent instance
    must delegate to the root's save()/reload() rather than acting on
    themselves, and save_as() called on a nested instance must re-root it to
    itself."""
    root_path = tmp_path / "nested_root.yml"

    child = MockedPersistentModel(
        a_file_path=Path("child.txt"),
        a_text_content="child original",
    )
    root = MockedPersistentModel(
        a_file_path=Path("root.txt"),
        a_text_content="root original",
        a_persistent_model=child,
    )
    root.save_as(root_path)

    assert child.persistent is root

    # save() on a non-root nested instance delegates to the root's save()
    child.a_text_content = "child changed"
    child.save()

    reloaded = MockedPersistentModel.load(root_path)
    assert reloaded.a_persistent_model.a_text_content == "child changed"

    # reload() on a non-root nested instance delegates to the root's reload()
    root.a_text_content = "root changed in memory only"
    child.reload()
    assert root.a_text_content == "root original"

    # save_as() on a non-root nested instance re-roots it to itself
    new_path = tmp_path / "child_as_new_root.yml"
    child.save_as(new_path)

    assert child.persistent is child
    assert child.settings_path == new_path
    assert new_path.exists()