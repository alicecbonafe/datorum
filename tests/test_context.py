from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from datorum.context import (
    DOC_HANDLERS,
    DOC_MODELS,
    DOC_TYPES,
    DocumentContext,
    DocumentHandler,
    DocumentModel,
    DocumentReference,
    doc_model,
    find_handlers,
    get_or_create_handler,
    register_doc_type,
    register_pydantic_based_handler,
)
from datorum.exceptions import (
    ConfigException,
    DocumentFormatException,
    DocumentNotFoundException,
    UnknownDataModelException,
)


@pytest.mark.depends(on=["tests/test_base_settings.py"])
def test_registry(tmp_path: Path):
    doc_type = "text/test"
    doc_extentions = ["tst", "test"]

    doc_path = tmp_path / "test_registry.json"
    content_test = "Mocked Content"

    class PydanticBasedModel(BaseModel):
        var_test: str = ""

    register_doc_type(
        id=doc_type,
        extentions=doc_extentions
    )

    assert DOC_TYPES[doc_type].extentions == doc_extentions

    register_pydantic_based_handler(
        model_type=PydanticBasedModel,
    )
    registry_pydantic_handler = get_or_create_handler(
        doc_type="application/json",
        doc_model=PydanticBasedModel.__name__,
    )

    assert ("application/json", PydanticBasedModel.__name__) == registry_pydantic_handler.id

    obj1 = PydanticBasedModel(var_test=content_test)
    registry_pydantic_handler.serializer(obj1, doc_path)
    obj2 = registry_pydantic_handler.deserializer(doc_path)

    assert isinstance(obj2, PydanticBasedModel)
    assert obj1.var_test == obj2.var_test

    with pytest.raises(DocumentFormatException, match=r"^No dict serializer.*?$"):
        register_pydantic_based_handler(
            model_type=PydanticBasedModel,
            doc_type=doc_type
        )

    assert len(find_handlers()) > 3
    assert len(find_handlers(doc_type=doc_type)) == 0
    assert len(find_handlers(
        doc_model=PydanticBasedModel.__name__)) == 3
    assert len(find_handlers(
        doc_type="application/json",
        doc_model=PydanticBasedModel.__name__)) == 1

    @doc_model(id="mocked-model-1", doc_type="application/json")
    class MockedModel1(BaseModel): ...

    @doc_model(id="mocked-model-2", doc_type="application/yaml")
    class MockedModel2: ...

@pytest.mark.depends(on=["test_registry"])
def test_defaults(tmp_path: Path):
    text_file = tmp_path / "mocked.txt"
    json_file = tmp_path / "mocked.json"
    yaml_file = tmp_path / "mocked.yaml"
    toml_file = tmp_path / "mocked.toml"

    data = {
        "test1": "some value",
        "test2": 10
    }

    assert not text_file.exists()
    assert not json_file.exists()
    assert not yaml_file.exists()
    assert not toml_file.exists()

    text_handler = DOC_HANDLERS[("text/plain", "text")]
    json_handler = DOC_HANDLERS[("application/json", "dict")]
    yaml_handler = DOC_HANDLERS[("application/yaml", "dict")]
    toml_handler = DOC_HANDLERS[("application/toml", "dict")]

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
def test_document_reference(tmp_path: Path):
    text_content = "Mocked Data!!!"

    document_id = "domain_1.domain_2.mocked_doc"
    document = DocumentReference(id=document_id)
    context: DocumentContext = DocumentContext.model_validate({"id": "mocked-context", "documents": {document_id: document}})
    assert document_id in context.documents
    context.base_path = tmp_path

    assert document.base_path == tmp_path

    assert document.registry_doc_type.id == "text/plain"
    assert document.registry_doc_model.id == "text"
    assert document.registry_doc_handler.id == ("text/plain", "text")

    assert document.name == "mocked_doc"
    assert document.domain_list == ["domain_1", "domain_2"]
    assert document.domain == "domain_1.domain_2"

    doc_path = document.doc_path
    assert str(doc_path).endswith(".txt")

    assert not doc_path.exists()
    document.save(text_content)
    assert doc_path.exists()

    text_content_1 = document.load()
    assert text_content == text_content_1

    document_2 = context.create_document(id="domain_3.mocked_doc")
    document.copy_to(document_2)
    text_content_2 = document_2.load()
    assert text_content == text_content_2

    document_error = DocumentReference(
        id="mocked_err",
        doc_type="not/found",
        doc_model="missing"
    )


    with pytest.raises(DocumentFormatException):
        assert document_error.registry_doc_type

    with pytest.raises(UnknownDataModelException):
        assert document_error.registry_doc_model

    with pytest.raises(DocumentFormatException):
        assert document_error.registry_doc_handler

    with pytest.raises(ValueError, match=r"out of context$"):
        assert document_error.base_path

    document_error._context = context
    register_doc_type("not/found", [".none"])
    with pytest.raises(DocumentNotFoundException):
        document_error.load()

    document_error.doc_path.touch()
    id_error = ("not/found", "missing")
    DOC_HANDLERS[id_error] = DocumentHandler(
        doc_type="not/found",
        doc_model="missing",
    )
    with pytest.raises(DocumentFormatException):
        document_error.load()

    DOC_MODELS["missing"] = DocumentModel(
        id="missing",
        clazz=DocumentModel,
        default_doc_type="not/found"
    )
    with pytest.raises(TypeError):
        document_error.save(text_content)

    DOC_MODELS["missing"].clazz = str
    with pytest.raises(DocumentFormatException):
        document_error.save(text_content)


    @doc_model(id="mocked")
    class MockedModel(BaseModel):
        a_text: str
        a_list: list[str] = Field(default_factory=list)

    document_1 = context.create_document(
        id="domain_1.mocked",
        doc_type="application/json",
        doc_model=MockedModel.__name__
    )

    document_2 = context.create_document(
        id="domain_1.mocked",
        doc_type="application/yaml",
        doc_model=MockedModel.__name__
    )

    model_1 = MockedModel(a_text = text_content)
    document_1.save(model_1)
    document_1.copy_to(document_2)
    model_2: MockedModel = document_2.load()
    assert model_1.a_text == model_2.a_text

    document_3 = DocumentReference(id="error.mocked")
    with pytest.raises(DocumentFormatException):
        document_1.copy_to(document_3)

    document_1.doc_path.unlink()
    with pytest.raises(DocumentNotFoundException):
        document_1.copy_to(document_2)

@pytest.mark.depends(on=["test_document_reference"])
def test_document_context(tmp_path: Path):
    context_1 = DocumentContext(id="context-1")

    with pytest.raises(ConfigException):
        assert context_1.base_path

    document_1_id = "domain.document"
    document_1 = context_1.create_document(id=document_1_id)
    assert context_1.get_document(document_1_id) is document_1

    context_1.base_path = tmp_path / "context_1_files"
    assert context_1.base_path == document_1.base_path

    document_2_id = "alt_domain.new_document"
    document_2 = context_1.create_document(document_2_id)
    assert context_1.get_document(document_2_id) is document_2

    document_2.save("Mocked Data!!!")
    assert document_2.doc_path.exists()
    context_1.drop_document(document_2_id, remove_file=True)
    assert context_1.get_document(document_2_id) is None
    assert not document_2.doc_path.exists()