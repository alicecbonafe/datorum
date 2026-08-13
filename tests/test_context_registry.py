from pathlib import Path

import pytest
from pydantic import BaseModel

from datorum.context.registry import (
    DocumentHandlerRegistry,
    DocumentModelRegistry,
    DocumentTypeRegistry,
    DocumentHandler,
    DocumentModel,
    doc_model,
    find_handlers,
    register_doc_type,
    register_doc_model,
    register_pydantic_based_handler,
    get_doc_type,
    get_doc_model,
    get_or_create_handler,
    MarkdownDocument,
)
from datorum.core.exceptions import DocumentFormatException, InvalidIdentifierException


def test_registry(tmp_path: Path):
    doc_type = "text/test"
    doc_extentions = ["tst", "test"]

    doc_model_id = "test"
    doc_model_clazz = str

    doc_path = tmp_path / "test_registry.json"
    content_test = "Mocked Content"

    class PydanticBasedModel(BaseModel):
        var_test: str = ""

    register_doc_type(id=doc_type, extentions=doc_extentions)

    assert DocumentTypeRegistry[doc_type].extentions == doc_extentions
    assert get_doc_type(doc_type).extentions == doc_extentions

    with pytest.raises(DocumentFormatException, match=r"^Doc type '.*?' is already registered$"):
        register_doc_type(id=doc_type, extentions=doc_extentions)
    with pytest.raises(InvalidIdentifierException, match=r"^Doc type '.*?' not found in registry$"):
        get_doc_type(id="invalid")

    register_doc_model(id=doc_model_id, clazz=doc_model_clazz, default_doc_type=doc_type)

    assert DocumentModelRegistry[doc_model_id].clazz is doc_model_clazz
    assert get_doc_model(doc_model_id).clazz == doc_model_clazz

    with pytest.raises(DocumentFormatException, match=r"^Doc model '.*?' is already registered$"):
        register_doc_model(id=doc_model_id, clazz=doc_model_clazz)
    with pytest.raises(InvalidIdentifierException, match=r"^Doc model '.*?' not found in registry$"):
        get_doc_model(id="invalid")

    register_pydantic_based_handler(
        model_type=PydanticBasedModel,
    )
    registry_pydantic_handler = get_or_create_handler(
        doc_type="application/json",
        doc_model=PydanticBasedModel.__name__,
    )

    assert (
        "application/json",
        PydanticBasedModel.__name__,
    ) == registry_pydantic_handler.id

    obj1 = PydanticBasedModel(var_test=content_test)
    assert registry_pydantic_handler.serializer is not None
    assert registry_pydantic_handler.deserializer is not None
    registry_pydantic_handler.serializer(obj1, doc_path)
    obj2 = registry_pydantic_handler.deserializer(doc_path)

    assert isinstance(obj2, PydanticBasedModel)
    assert obj1.var_test == obj2.var_test

    with pytest.raises(DocumentFormatException, match=r"^No dict serializer.*?$"):
        register_pydantic_based_handler(
            model_type=PydanticBasedModel, doc_type=doc_type
        )

    assert len(find_handlers()) > 3
    assert len(find_handlers(doc_type=doc_type)) == 0
    assert len(find_handlers(doc_model=PydanticBasedModel.__name__)) == 3
    assert (
        len(
            find_handlers(
                doc_type="application/json", doc_model=PydanticBasedModel.__name__
            )
        )
        == 1
    )

    @doc_model(id="mocked-model-1", doc_type="application/json")
    class MockedModel1(BaseModel): ...

    @doc_model(id="mocked-model-2", doc_type="application/yaml")
    class MockedModel2: ...

    with pytest.raises(DocumentFormatException, match=r"^Doc model '.*?' is already registrered"):
        @doc_model(id="mocked-model-1")
        class NotRegisteredMockedModel: ...


@pytest.mark.depends(on=["test_registry"])
def test_defaults(tmp_path: Path):
    text_file = tmp_path / "mocked.txt"
    json_file = tmp_path / "mocked.json"
    yaml_file = tmp_path / "mocked.yaml"
    toml_file = tmp_path / "mocked.toml"

    data = {"test1": "some value", "test2": 10}

    assert not text_file.exists()
    assert not json_file.exists()
    assert not yaml_file.exists()
    assert not toml_file.exists()

    text_handler = DocumentHandlerRegistry[("text/plain", "text")]
    json_handler = DocumentHandlerRegistry[("application/json", "dict")]
    yaml_handler = DocumentHandlerRegistry[("application/yaml", "dict")]
    toml_handler = DocumentHandlerRegistry[("application/toml", "dict")]

    assert text_handler.serializer is not None
    assert json_handler.serializer is not None
    assert yaml_handler.serializer is not None
    assert toml_handler.serializer is not None
    assert text_handler.deserializer is not None
    assert json_handler.deserializer is not None
    assert yaml_handler.deserializer is not None
    assert toml_handler.deserializer is not None

    text_handler.serializer(str(data), text_file)
    json_handler.serializer(data, json_file)
    yaml_handler.serializer(data, yaml_file)
    toml_handler.serializer(data, toml_file)

    assert text_file.exists()
    assert json_file.exists()
    assert yaml_file.exists()
    assert toml_file.exists()

    text_data = text_handler.deserializer(text_file)
    json_data = json_handler.deserializer(json_file)
    yaml_data = yaml_handler.deserializer(yaml_file)
    toml_data = toml_handler.deserializer(toml_file)

    assert text_data == str(data)
    assert json_data == data
    assert yaml_data == data
    assert toml_data == data


@pytest.mark.depends(on=["test_defaults"])
def test_markdown(tmp_path: Path):
    markdown_file = tmp_path / "test.md"
    frontmatter = {"title": "Mocked MarkDown", "author": "Mocked Author"}
    content = "# Simple MarkDown\n\nThis is a simple markdown file."

    doc = MarkdownDocument(
        content=content,
        frontmatter=frontmatter,
    )

    doc_str = doc.dumps()
    assert doc_str.startswith(MarkdownDocument.DELIMITER_YAML)
    assert doc_str.find(content) > 0
    assert doc_str.find(frontmatter["title"]) > 0
    doc_2 = MarkdownDocument.loads(doc_str)
    assert doc.content == doc_2.content
    assert doc.frontmatter == doc_2.frontmatter
    assert doc.frontmatter_format == doc_2.frontmatter_format

    doc.frontmatter_format = MarkdownDocument.FRONTMATTER_JSON
    doc_str = doc.dumps()
    assert doc_str.startswith(MarkdownDocument.DELIMITER_JSON)
    doc_2 = MarkdownDocument.loads(doc_str)
    assert doc.content == doc_2.content
    assert doc.frontmatter == doc_2.frontmatter
    assert doc.frontmatter_format == doc_2.frontmatter_format

    doc.frontmatter_format = MarkdownDocument.FRONTMATTER_TOML
    doc_str = doc.dumps()
    assert doc_str.startswith(MarkdownDocument.DELIMITER_TOML)
    doc_2 = MarkdownDocument.loads(doc_str)
    assert doc.content == doc_2.content
    assert doc.frontmatter == doc_2.frontmatter
    assert doc.frontmatter_format == doc_2.frontmatter_format

    doc.dump(markdown_file)
    assert markdown_file.exists()
    doc_2 = MarkdownDocument.load(markdown_file)
    assert doc.content == doc_2.content
    assert doc.frontmatter == doc_2.frontmatter
    assert doc.frontmatter_format == doc_2.frontmatter_format

    handler = get_or_create_handler(
        doc_type="text/markdown",
        doc_model="markdown"
    )
    handler.serializer(doc_2, markdown_file)
    doc_3 = handler.deserializer(markdown_file)
    assert doc_2.content == doc_3.content
    assert doc_2.frontmatter == doc_3.frontmatter
    assert doc_2.frontmatter_format == doc_3.frontmatter_format
    


