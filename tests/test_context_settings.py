from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from datorum.core.exceptions import SettingsError
from datorum.context.settings import (
    DocumentContext,
    DocumentReference,
)
from datorum.context.registry import (
    DocumentModel,
    DocumentModelRegistry,
    DocumentHandler,
    DocumentHandlerRegistry,
    register_doc_type,
    doc_model,
)
from datorum.context.exceptions import (
    DocumentTypeError,
    DocumentModelError,
    DocumentHandlerError,
    DocumentReferenceError,
    DocumentReadingError,
    DocumentWritingError,
)
from datorum.core.settings import BaseDatorumPersistentSettings


@pytest.mark.depends(on=[
    "tests/test_core_settings.py",
    "tests/test_context_registry.py",
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

    with pytest.raises(DocumentTypeError):
        assert document_error.registry_doc_type

    with pytest.raises(DocumentModelError):
        assert document_error.registry_doc_model

    with pytest.raises(DocumentHandlerError):
        assert document_error.registry_doc_handler

    with pytest.raises(SettingsError, match="Persistent model not defined"):
        assert document_error.base_path

    document_error._persistent = context
    register_doc_type("not/found", [".none"])
    with pytest.raises(DocumentReadingError):
        document_error.load()
    with pytest.raises(DocumentTypeError):
        register_doc_type("not/found", [".none"])

    document_error.doc_path.touch()
    id_error = ("not/found", "missing")
    DocumentHandlerRegistry[id_error] = DocumentHandler(
        doc_type="not/found",
        doc_model="missing",
    )
    with pytest.raises(DocumentReadingError):
        document_error.load()

    DocumentModelRegistry["missing"] = DocumentModel(
        id="missing", clazz=DocumentModel, default_doc_type="not/found"
    )
    with pytest.raises(TypeError):
        document_error.save(text_content)

    DocumentModelRegistry["missing"].clazz = str
    with pytest.raises(DocumentWritingError):
        document_error.save(text_content)

    with pytest.raises(DocumentModelError):
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
    with pytest.raises(DocumentWritingError):
        document_1.copy_to(document_3)

    document_1.doc_path.unlink()
    with pytest.raises(DocumentWritingError):
        document_1.copy_to(document_2)


@pytest.mark.depends(on=["test_document_reference"])
def test_document_context(tmp_path: Path):
    context_1 = DocumentContext(id="context-1")

    with pytest.raises(SettingsError):
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

    document_1._persistent = BaseDatorumPersistentSettings()
    with pytest.raises(DocumentReferenceError, match=f"Document out of context: '{document_1.id}'"):
        assert document_1.context

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

@pytest.mark.depends(on=["test_special_cases"])
def test_document_reference_extension_resolution(tmp_path: Path):
    """Covers the three ways DocumentReference._decompose_id() can resolve
    an extension: explicit `extension` field, an extension embedded as the
    id's trailing segment, and falling back to the doc_type's default."""
    context = DocumentContext(id="ctx-extension-resolution")
    context.base_path = tmp_path

    # Explicit `extension` field wins outright and is stripped from the id
    # before splitting into domain/name.
    doc_explicit = DocumentReference(id="domain.name", extension="md")
    doc_explicit._set_persistent_recursive(context)
    assert doc_explicit.domain_list == ["domain"]
    assert doc_explicit.name == "name"
    assert doc_explicit.doc_path == tmp_path / "domain" / "name.md"

    # No explicit extension, but the id's trailing segment already matches
    # one of the doc_type's registered extensions ("txt" for text/plain):
    # that segment is treated as the extension rather than part of the name.
    doc_embedded = DocumentReference(id="domain.name.txt")
    doc_embedded._set_persistent_recursive(context)
    assert doc_embedded.domain_list == ["domain"]
    assert doc_embedded.name == "name"
    assert doc_embedded.doc_path == tmp_path / "domain" / "name.txt"

    # No explicit extension and the trailing segment isn't a known
    # extension: falls back to the doc_type's default (first) extension.
    doc_default = DocumentReference(id="domain.name")
    doc_default._set_persistent_recursive(context)
    assert doc_default.domain_list == ["domain"]
    assert doc_default.name == "name"
    assert doc_default.doc_path == tmp_path / "domain" / "name.txt"