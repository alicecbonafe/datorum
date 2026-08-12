from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from datorum.settings.context import (
    DocumentContext,
    DocumentReference,
    ContextBindType,
)
from datorum.registry.documents import (
    DocumentModel,
    DocumentModelRegistry,
    DocumentHandler,
    DocumentHandlerRegistry,
    register_doc_type,
    doc_model,
)
from datorum.exceptions import (
    ConfigException,
    DocumentFormatException,
    DocumentNotFoundException,
    UnknownDataModelException,
    NoFilePathException,
)
from datorum.settings.base import BaseDatorumPersistentSettings


@pytest.mark.depends(on=[
    "tests/test_settings_base.py",
    "tests/test_registry_documents.py",
])
def test_document_reference(tmp_path: Path):
    text_content = "Mocked Data!!!"

    document_id = "domain_1.domain_2.mocked_doc"
    document = DocumentReference(id=document_id)
    context: DocumentContext = DocumentContext.model_validate(
        {"id": "mocked-context", "documents": {document_id: document}}
    )
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
        id="mocked_err", doc_type="not/found", doc_model="missing"
    )

    with pytest.raises(DocumentFormatException):
        assert document_error.registry_doc_type

    with pytest.raises(UnknownDataModelException):
        assert document_error.registry_doc_model

    with pytest.raises(DocumentFormatException):
        assert document_error.registry_doc_handler

    with pytest.raises(ConfigException, match="Persistent model not defined"):
        assert document_error.base_path

    document_error._persistent = context
    register_doc_type("not/found", [".none"])
    with pytest.raises(DocumentNotFoundException):
        document_error.load()
    with pytest.raises(DocumentFormatException):
        register_doc_type("not/found", [".none"])

    document_error.doc_path.touch()
    id_error = ("not/found", "missing")
    DocumentHandlerRegistry[id_error] = DocumentHandler(
        doc_type="not/found",
        doc_model="missing",
    )
    with pytest.raises(DocumentFormatException):
        document_error.load()

    DocumentModelRegistry["missing"] = DocumentModel(
        id="missing", clazz=DocumentModel, default_doc_type="not/found"
    )
    with pytest.raises(TypeError):
        document_error.save(text_content)

    DocumentModelRegistry["missing"].clazz = str
    with pytest.raises(DocumentFormatException):
        document_error.save(text_content)

    with pytest.raises(DocumentFormatException):
        @doc_model(id="missing")
        class OverwriteFailMocked:...

    @doc_model(id="MockedModel")
    class MockedModel(BaseModel):
        a_text: str
        a_list: list[str] = Field(default_factory=list)

    document_1 = context.create_document(
        id="domain_1.mocked",
        doc_type="application/json",
        doc_model=MockedModel.__name__,
    )

    document_2 = context.create_document(
        id="domain_1.mocked",
        doc_type="application/yaml",
        doc_model=MockedModel.__name__,
    )

    model_1 = MockedModel(a_text=text_content)
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

    with pytest.raises(NoFilePathException):
        assert context_1.base_path

    document_1_id = "domain.document"
    document_1 = context_1.create_document(id=document_1_id)
    assert context_1.get_document(document_1_id) is document_1
    assert context_1.knows_domain("domain")

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

    domain = "other.domain"
    assert context_1.get_domain_metadata(domain) is None
    domain_metadata = {"author": "Mocked Author"}
    context_1.set_domain_metadata(domain, domain_metadata)
    assert context_1.knows_domain(domain)
    assert context_1.get_domain_path(domain) == context_1.base_path / "other" / "domain"
    assert context_1.get_domain_metadata(domain)["author"] == "Mocked Author"

@pytest.mark.depends(on=["test_document_context"])
def test_special_cases(tmp_path: Path):
    settings_path = tmp_path / "settings.yml"
    document_1_id = "mocked_document"
    document_1 = DocumentReference(id=document_1_id)

    class OtherSettings(BaseDatorumPersistentSettings):
        doc: DocumentReference

    settings = OtherSettings(doc=document_1)
    settings.save_as(settings_path)

    assert document_1.base_path == tmp_path
    

def test_content_types():
    assert not ContextBindType.model.is_domain()
    assert ContextBindType.model.is_input()
    assert ContextBindType.model.is_output()
    assert ContextBindType.model.is_model()
    assert not ContextBindType.model.is_text()
    assert not ContextBindType.model.is_bytes()
    assert not ContextBindType.model.is_path()
    assert not ContextBindType.model.is_metadata()
    assert ContextBindType.model.is_io()

    assert not ContextBindType.model_input.is_domain()
    assert ContextBindType.model_input.is_input()
    assert not ContextBindType.model_input.is_output()
    assert ContextBindType.model_input.is_model()
    assert not ContextBindType.model_input.is_text()
    assert not ContextBindType.model_input.is_bytes()
    assert not ContextBindType.model_input.is_path()
    assert not ContextBindType.model_input.is_metadata()
    assert ContextBindType.model_input.is_io()

    assert not ContextBindType.model_output.is_domain()
    assert not ContextBindType.model_output.is_input()
    assert ContextBindType.model_output.is_output()
    assert ContextBindType.model_output.is_model()
    assert not ContextBindType.model_output.is_text()
    assert not ContextBindType.model_output.is_bytes()
    assert not ContextBindType.model_output.is_path()
    assert not ContextBindType.model_output.is_metadata()
    assert ContextBindType.model_output.is_io()

    assert not ContextBindType.text.is_domain()
    assert ContextBindType.text.is_input()
    assert ContextBindType.text.is_output()
    assert not ContextBindType.text.is_model()
    assert ContextBindType.text.is_text()
    assert not ContextBindType.text.is_bytes()
    assert not ContextBindType.text.is_path()
    assert not ContextBindType.text.is_metadata()
    assert ContextBindType.text.is_io()

    assert not ContextBindType.text_input.is_domain()
    assert ContextBindType.text_input.is_input()
    assert not ContextBindType.text_input.is_output()
    assert not ContextBindType.text_input.is_model()
    assert ContextBindType.text_input.is_text()
    assert not ContextBindType.text_input.is_bytes()
    assert not ContextBindType.text_input.is_path()
    assert not ContextBindType.text_input.is_metadata()
    assert ContextBindType.text_input.is_io()

    assert not ContextBindType.text_output.is_domain()
    assert not ContextBindType.text_output.is_input()
    assert ContextBindType.text_output.is_output()
    assert not ContextBindType.text_output.is_model()
    assert ContextBindType.text_output.is_text()
    assert not ContextBindType.text_output.is_bytes()
    assert not ContextBindType.text_output.is_path()
    assert not ContextBindType.text_output.is_metadata()
    assert ContextBindType.text_output.is_io()

    assert not ContextBindType.bytes.is_domain()
    assert ContextBindType.bytes.is_input()
    assert ContextBindType.bytes.is_output()
    assert not ContextBindType.bytes.is_model()
    assert not ContextBindType.bytes.is_text()
    assert ContextBindType.bytes.is_bytes()
    assert not ContextBindType.bytes.is_path()
    assert not ContextBindType.bytes.is_metadata()
    assert ContextBindType.bytes.is_io()

    assert not ContextBindType.bytes_input.is_domain()
    assert ContextBindType.bytes_input.is_input()
    assert not ContextBindType.bytes_input.is_output()
    assert not ContextBindType.bytes_input.is_model()
    assert not ContextBindType.bytes_input.is_text()
    assert ContextBindType.bytes_input.is_bytes()
    assert not ContextBindType.bytes_input.is_path()
    assert not ContextBindType.bytes_input.is_metadata()
    assert ContextBindType.bytes_input.is_io()

    assert not ContextBindType.bytes_output.is_domain()
    assert not ContextBindType.bytes_output.is_input()
    assert ContextBindType.bytes_output.is_output()
    assert not ContextBindType.bytes_output.is_model()
    assert not ContextBindType.bytes_output.is_text()
    assert ContextBindType.bytes_output.is_bytes()
    assert not ContextBindType.bytes_output.is_path()
    assert not ContextBindType.bytes_output.is_metadata()
    assert ContextBindType.bytes_output.is_io()

    assert not ContextBindType.document_path.is_domain()
    assert ContextBindType.document_path.is_input()
    assert not ContextBindType.document_path.is_output()
    assert not ContextBindType.document_path.is_model()
    assert not ContextBindType.document_path.is_text()
    assert not ContextBindType.document_path.is_bytes()
    assert ContextBindType.document_path.is_path()
    assert not ContextBindType.document_path.is_metadata()
    assert not ContextBindType.document_path.is_io()

    assert not ContextBindType.document_metadata.is_domain()
    assert ContextBindType.document_metadata.is_input()
    assert ContextBindType.document_metadata.is_output()
    assert not ContextBindType.document_metadata.is_model()
    assert not ContextBindType.document_metadata.is_text()
    assert not ContextBindType.document_metadata.is_bytes()
    assert not ContextBindType.document_metadata.is_path()
    assert ContextBindType.document_metadata.is_metadata()
    assert not ContextBindType.document_metadata.is_io()

    assert ContextBindType.domain_path.is_domain()
    assert ContextBindType.domain_path.is_input()
    assert not ContextBindType.domain_path.is_output()
    assert not ContextBindType.domain_path.is_model()
    assert not ContextBindType.domain_path.is_text()
    assert not ContextBindType.domain_path.is_bytes()
    assert ContextBindType.domain_path.is_path()
    assert not ContextBindType.domain_path.is_metadata()
    assert not ContextBindType.domain_path.is_io()

    assert ContextBindType.domain_metadata.is_domain()
    assert ContextBindType.domain_metadata.is_input()
    assert ContextBindType.domain_metadata.is_output()
    assert not ContextBindType.domain_metadata.is_model()
    assert not ContextBindType.domain_metadata.is_text()
    assert not ContextBindType.domain_metadata.is_bytes()
    assert not ContextBindType.domain_metadata.is_path()
    assert ContextBindType.domain_metadata.is_metadata()
    assert not ContextBindType.domain_metadata.is_io()
