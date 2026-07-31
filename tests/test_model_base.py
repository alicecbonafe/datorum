from pathlib import Path

from datorum.model.base import BaseDatorumPersistentModel
from datorum.exceptions import NoFilePathException


class MockedPersistentModel(BaseDatorumPersistentModel):

    a_file_path: Path
    a_text_content: str


def test_persistence(tmp_path: Path):
    model_path = tmp_path / "model.yml"
    file_path = Path("test.txt")
    file_content = "Persistence ok!"
    text_content = "This goes inside the YAML file."

    (tmp_path / file_path).write_text(file_content, encoding="utf-8")

    data1 = MockedPersistentModel(
        a_file_path=file_path,
        a_text_content=text_content,
    )
    data1.save(str(model_path))

    data2: MockedPersistentModel = MockedPersistentModel.load(str(model_path))
    assert data2.a_file_path == file_path
    assert data2.a_text_content == text_content

    file_content2 = (tmp_path / data2.a_file_path).read_text(encoding="utf-8")
    assert file_content == file_content2

def test_exception():
    data = MockedPersistentModel(
        a_file_path=Path("test.yml"),
        a_text_content="test",
    )
    error_ok = False
    try:
        assert data.filepath
    except NoFilePathException:
        error_ok = True
    assert error_ok


