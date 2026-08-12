from pathlib import Path
from typing import Any, Optional

import pytest

from datorum.binding import (
    ContentType,
    validate_factory_signature,
    resource, get_resource_factory,
    ContextBind, ResourceBind,
    Binder,
)
from datorum.context import (
    DocumentReference,
    DocumentContext,
    register_doc_type,
    serializer, deserializer,
)
from datorum.exceptions import (
    InvalidContextBindException,
    InvalidResourceException,
)


@pytest.mark.depends(on=["tests/test_context.py"])
def test_content_types():
    assert not ContentType.model.is_domain()
    assert ContentType.model.is_input()
    assert ContentType.model.is_output()
    assert ContentType.model.is_model()
    assert not ContentType.model.is_text()
    assert not ContentType.model.is_bytes()
    assert not ContentType.model.is_path()
    assert not ContentType.model.is_metadata()
    assert ContentType.model.is_io()

    assert not ContentType.model_input.is_domain()
    assert ContentType.model_input.is_input()
    assert not ContentType.model_input.is_output()
    assert ContentType.model_input.is_model()
    assert not ContentType.model_input.is_text()
    assert not ContentType.model_input.is_bytes()
    assert not ContentType.model_input.is_path()
    assert not ContentType.model_input.is_metadata()
    assert ContentType.model_input.is_io()

    assert not ContentType.model_output.is_domain()
    assert not ContentType.model_output.is_input()
    assert ContentType.model_output.is_output()
    assert ContentType.model_output.is_model()
    assert not ContentType.model_output.is_text()
    assert not ContentType.model_output.is_bytes()
    assert not ContentType.model_output.is_path()
    assert not ContentType.model_output.is_metadata()
    assert ContentType.model_output.is_io()

    assert not ContentType.text.is_domain()
    assert ContentType.text.is_input()
    assert ContentType.text.is_output()
    assert not ContentType.text.is_model()
    assert ContentType.text.is_text()
    assert not ContentType.text.is_bytes()
    assert not ContentType.text.is_path()
    assert not ContentType.text.is_metadata()
    assert ContentType.text.is_io()

    assert not ContentType.text_input.is_domain()
    assert ContentType.text_input.is_input()
    assert not ContentType.text_input.is_output()
    assert not ContentType.text_input.is_model()
    assert ContentType.text_input.is_text()
    assert not ContentType.text_input.is_bytes()
    assert not ContentType.text_input.is_path()
    assert not ContentType.text_input.is_metadata()
    assert ContentType.text_input.is_io()

    assert not ContentType.text_output.is_domain()
    assert not ContentType.text_output.is_input()
    assert ContentType.text_output.is_output()
    assert not ContentType.text_output.is_model()
    assert ContentType.text_output.is_text()
    assert not ContentType.text_output.is_bytes()
    assert not ContentType.text_output.is_path()
    assert not ContentType.text_output.is_metadata()
    assert ContentType.text_output.is_io()

    assert not ContentType.bytes.is_domain()
    assert ContentType.bytes.is_input()
    assert ContentType.bytes.is_output()
    assert not ContentType.bytes.is_model()
    assert not ContentType.bytes.is_text()
    assert ContentType.bytes.is_bytes()
    assert not ContentType.bytes.is_path()
    assert not ContentType.bytes.is_metadata()
    assert ContentType.bytes.is_io()

    assert not ContentType.bytes_input.is_domain()
    assert ContentType.bytes_input.is_input()
    assert not ContentType.bytes_input.is_output()
    assert not ContentType.bytes_input.is_model()
    assert not ContentType.bytes_input.is_text()
    assert ContentType.bytes_input.is_bytes()
    assert not ContentType.bytes_input.is_path()
    assert not ContentType.bytes_input.is_metadata()
    assert ContentType.bytes_input.is_io()

    assert not ContentType.bytes_output.is_domain()
    assert not ContentType.bytes_output.is_input()
    assert ContentType.bytes_output.is_output()
    assert not ContentType.bytes_output.is_model()
    assert not ContentType.bytes_output.is_text()
    assert ContentType.bytes_output.is_bytes()
    assert not ContentType.bytes_output.is_path()
    assert not ContentType.bytes_output.is_metadata()
    assert ContentType.bytes_output.is_io()

    assert not ContentType.document_path.is_domain()
    assert ContentType.document_path.is_input()
    assert not ContentType.document_path.is_output()
    assert not ContentType.document_path.is_model()
    assert not ContentType.document_path.is_text()
    assert not ContentType.document_path.is_bytes()
    assert ContentType.document_path.is_path()
    assert not ContentType.document_path.is_metadata()
    assert not ContentType.document_path.is_io()

    assert not ContentType.document_metadata.is_domain()
    assert ContentType.document_metadata.is_input()
    assert ContentType.document_metadata.is_output()
    assert not ContentType.document_metadata.is_model()
    assert not ContentType.document_metadata.is_text()
    assert not ContentType.document_metadata.is_bytes()
    assert not ContentType.document_metadata.is_path()
    assert ContentType.document_metadata.is_metadata()
    assert not ContentType.document_metadata.is_io()

    assert ContentType.domain_path.is_domain()
    assert ContentType.domain_path.is_input()
    assert not ContentType.domain_path.is_output()
    assert not ContentType.domain_path.is_model()
    assert not ContentType.domain_path.is_text()
    assert not ContentType.domain_path.is_bytes()
    assert ContentType.domain_path.is_path()
    assert not ContentType.domain_path.is_metadata()
    assert not ContentType.domain_path.is_io()

    assert ContentType.domain_metadata.is_domain()
    assert ContentType.domain_metadata.is_input()
    assert ContentType.domain_metadata.is_output()
    assert not ContentType.domain_metadata.is_model()
    assert not ContentType.domain_metadata.is_text()
    assert not ContentType.domain_metadata.is_bytes()
    assert not ContentType.domain_metadata.is_path()
    assert ContentType.domain_metadata.is_metadata()
    assert not ContentType.domain_metadata.is_io()


@pytest.mark.depends(on=["test_content_types"])
def test_registry():
    def mocked_func_valid_1(param: str | None):...
    def mocked_func_valid_2(param):...
    def mocked_func_valid_3(param: Any):...
    def mocked_func_valid_4(param: Optional[str]):...
    def mocked_func_valid_5(param: dict | str | type(None)):...

    def mocked_func_invalid_1():...
    def mocked_func_invalid_2(param: str):...
    def mocked_func_invalid_3(param: dict):...
    def mocked_func_invalid_4(*, param: str):...
    def mocked_func_invalid_5(*args):...
    def mocked_func_invalid_6(**kwargs):...
    def mocked_func_invalid_7(param: int | float): ...

    assert validate_factory_signature(mocked_func_valid_1)
    assert validate_factory_signature(mocked_func_valid_2)
    assert validate_factory_signature(mocked_func_valid_3)
    assert validate_factory_signature(mocked_func_valid_4)
    assert validate_factory_signature(mocked_func_valid_5)

    assert not validate_factory_signature(mocked_func_invalid_1)
    assert not validate_factory_signature(mocked_func_invalid_2)
    assert not validate_factory_signature(mocked_func_invalid_3)
    assert not validate_factory_signature(mocked_func_invalid_4)
    assert not validate_factory_signature(mocked_func_invalid_5)
    assert not validate_factory_signature(mocked_func_invalid_6)
    assert not validate_factory_signature(mocked_func_invalid_7)

    factory_name = "resource-factory-1"
    
    with pytest.raises(InvalidResourceException, match=r"^Resource factory.*?not found$"):
        get_resource_factory(factory_name)

    @resource(name=factory_name)
    def mocked_factory(selector: str | None):
        return f"Selected({selector})"

    assert get_resource_factory(factory_name) is mocked_factory
    assert get_resource_factory(factory_name)("!") == "Selected(!)"

    with pytest.raises(InvalidResourceException, match=r"^Resource factory.*?is already registered, use 'force=True' to overwrite$"):
        @resource(name=factory_name)
        def mocked_error(selector: str | None):...

    with pytest.raises(InvalidResourceException, match=r"^Resource factory.*?has not a compatible signature$"):
        @resource()
        def mocked_error():...


@pytest.mark.depends(on=["test_registry"])    
def test_binder(tmp_path: Path,):
    domain_1 = "domain_1"
    domain_2 = "domain_2"
    doc_1_id = "doc_1"
    doc_1_content = "Mocked content."
    doc_empty_id = "doc_empty"
    doc_bytes_id = "doc_bytes"
    doc_bytes_content = b"Mocked bytes."
    ctx_id = "context"
    domain_1_metadata = {"title": "Mocked Domain I"}

    register_doc_type("bin", ["bin"])
    @serializer(doc_type="bin", doc_model="bin")
    def bytes_serializer(data: bytes, file_path: Path):
        file_path.write_bytes(data)
    @deserializer(doc_type="bin", doc_model="bin")
    def bytes_deserializer(file_path: Path) -> bytes:
        return file_path.read_bytes(data)

    doc_1 = DocumentReference(id=f"{domain_1}.{domain_2}.{doc_1_id}")
    doc_empty = DocumentReference(id=f"{domain_1}.{doc_empty_id}")
    doc_bytes = DocumentReference(
        id=f"{domain_1}.{doc_bytes_id}",
        doc_type="bin", doc_model="bin",
    )
    ctx = DocumentContext(
        id=ctx_id,
        documents={
            doc_1.id: doc_1,
            doc_empty.id: doc_empty,
            doc_bytes.id: doc_bytes,
        },
        domain_metadata={domain_1: domain_1_metadata}
    )
    ctx.save_as(tmp_path / f"{ctx_id}.yml")
    doc_1.save(doc_1_content)
    doc_bytes.save(doc_bytes_content)  ############################################################################

    binder = Binder()
    binder.add_context(
        settings_path=tmp_path / f"{ctx_id}.yml",
        base_path=tmp_path
    )

    assert binder.find_domain_context(
        domain=f"{domain_1}.{domain_2}"
    ).id == ctx.id
    assert binder.find_domain_context(
        domain=f"{domain_1}.{domain_2}",
        context=ctx_id
    ).id == ctx.id
    assert binder.find_domain_context(
        domain=f"{domain_1}.{domain_2}",
        context=["invalid", ctx_id]
    ).id == ctx.id

    with pytest.raises(InvalidContextBindException, match=r"^Unknown context.*?"):
        binder.find_domain_context(domain=domain_1, context="invalid")
    with pytest.raises(InvalidContextBindException, match=r"^Unknown domain.*?"):
        binder.find_domain_context(domain="invalid", context=ctx_id)
    with pytest.raises(InvalidContextBindException, match=r"^Unknown domain.*?"):
        binder.find_domain_context(domain=domain_2)

    domain_1_path = binder.pull_context(ContextBind(
        binded_id=domain_1,
        content_type=ContentType.domain_path
    ))
    domain_1_metadata_1 = binder.pull_context(ContextBind(
        binded_id=domain_1,
        content_type=ContentType.domain_metadata
    ))

    assert domain_1_path == tmp_path / domain_1
    assert domain_1_metadata_1["title"] == domain_1_metadata["title"]

    doc_2 = binder.find_document(
        document_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=ctx_id,
    )
    doc_3 = binder.find_document(
        document_id=f"{domain_1}.{domain_2}.{doc_1_id}",
    )
    doc_4 = binder.find_document(
        document_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=["invalid", ctx_id],
    )

    assert doc_2.id == doc_1.id
    assert doc_2.doc_path == doc_1.doc_path
    assert doc_3.id == doc_1.id
    assert doc_3.doc_path == doc_1.doc_path
    assert doc_4.id == doc_1.id
    assert doc_4.doc_path == doc_1.doc_path

    with pytest.raises(InvalidContextBindException, match=r"^Unknown context.*?"):
        binder.find_document(document_id=doc_1_id, context="invalid")

    with pytest.raises(InvalidContextBindException, match=r"^Unknown document.*?"):
        binder.find_document(document_id="invalid")

    ctx_value_1 = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=ctx_id,
        content_type=ContentType.model,
    ))
    ctx_value_2 = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=["invalid", ctx_id],
        content_type=ContentType.model,
    ))
    ctx_value_text = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        content_type=ContentType.text,
    ))
    ctx_value_bytes = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        content_type=ContentType.bytes,
    ))

    assert ctx_value_1 == doc_1_content
    assert ctx_value_2 == doc_1_content
    assert ctx_value_3 == doc_1_content

    assert ctx_value_text == doc_1_content
    assert ctx_value_bytes == doc_bytes_content

    with pytest.raises(InvalidContextBindException, match=r"^Cannot pull from an output-only bind.*?"):
        ctx_bind_err = ContextBind(
            binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
            content_type=ContentType.model_output,
        )
        ctx_value_err = binder.pull_context(ctx_bind_err)

    with pytest.raises(InvalidContextBindException, match=r"^File not found for document.*?"):
        ctx_value_err = binder.pull_context(ContextBind(
            binded_id=f"{domain_1}.{doc_empty_id}",
            content_type=ContentType.model,
        ))

    @binder.resource()
    def factory_1(selector): ...

    with pytest.raises(InvalidResourceException, match=r"^Resource factory '.*?' is already registered, use 'force=True' to overwrite$"):
        @binder.resource(name="factory_1")
        def factory_error_1(selector): ...

    with pytest.raises(InvalidResourceException, match=r"^Resource factory '.*?' has not a compatible signature$"):
        @binder.resource()
        def factory_error_2(): ...



