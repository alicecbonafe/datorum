from pathlib import Path
from typing import Any, Optional

import pytest

from datorum.registry.documents import (
    register_doc_type,
    register_doc_model,
    serializer, deserializer,
)
from datorum.settings.context import (
    ContextBindType,
    ContextBind, ResourceBind,
    DocumentReference,
    DocumentContext,
)
from datorum.registry.resources import (
    validate_factory_signature,
    resource, get_resource_factory,
    Binder,
)
from datorum.exceptions import (
    InvalidContextBindException,
    InvalidResourceException,
)



@pytest.mark.depends(on=["test_registry"])    
def test_binder(tmp_path: Path,):
    domain_1 = "domain_1"
    domain_2 = "domain_2"
    doc_1_id = "doc_1"
    doc_1_content = "Mocked content."
    doc_1_content_changed = "Mocked content (changed)."
    doc_empty_id = "doc_empty"
    doc_bytes_id = "doc_bytes"
    doc_bytes_content = b"Mocked bytes."
    doc_bytes_content_changed = b"Mocked bytes (changed)."
    doc_bytes_metadata = {"title": "Bytes Mocked Document"}
    doc_bytes_metadata_changed = {"title": "Bytes Mocked Document (changed)"}
    ctx_id = "context"
    domain_1_metadata = {"title": "Mocked Domain I"}
    domain_1_metadata_changed = {"title": "Mocked Domain I (changed)"}

    register_doc_type("bin", extentions=["bin"])
    register_doc_model("bin", clazz=bytes, default_doc_type="bin")
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
        metadata=doc_bytes_metadata
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
    doc_bytes.save(doc_bytes_content)

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
        context_bind_type=ContextBindType.domain_path
    ))
    domain_1_metadata_1 = binder.pull_context(ContextBind(
        binded_id=domain_1,
        context_bind_type=ContextBindType.domain_metadata
    ))

    assert domain_1_path == tmp_path / domain_1
    assert domain_1_metadata_1["title"] == domain_1_metadata["title"]

    binder.push_context(ContextBind(
        binded_id=domain_1,
        context_bind_type=ContextBindType.domain_metadata
    ), domain_1_metadata_changed)

    assert binder.pull_context(ContextBind(
        binded_id=domain_1,
        context_bind_type=ContextBindType.domain_metadata
    ))["title"] == domain_1_metadata_changed["title"]

    with pytest.raises(InvalidContextBindException, match=r"^Cannot push to an input-only bind.*?"):
        binder.push_context(ContextBind(
            binded_id=domain_1,
            context_bind_type=ContextBindType.domain_path
        ), tmp_path)
    with pytest.raises(InvalidContextBindException, match=r"^Wrong metadata type.*?"):
        binder.push_context(ContextBind(
            binded_id=domain_1,
            context_bind_type=ContextBindType.domain_metadata
        ), tmp_path)

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
        context_bind_type=ContextBindType.model,
    ))
    ctx_value_2 = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=["invalid", ctx_id],
        context_bind_type=ContextBindType.model,
    ))
    ctx_value_3 = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context_bind_type=ContextBindType.model,
    ))
    ctx_value_text = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context_bind_type=ContextBindType.text,
    ))
    ctx_value_bytes = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        context_bind_type=ContextBindType.bytes,
    ))
    ctx_value_metadata = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        context_bind_type=ContextBindType.document_metadata,
    ))
    ctx_value_path = binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        context_bind_type=ContextBindType.document_path,
    ))
    doc_bytes_path = tmp_path / domain_1 / f"{doc_bytes_id}.bin"

    assert ctx_value_1 == doc_1_content
    assert ctx_value_2 == doc_1_content
    assert ctx_value_3 == doc_1_content

    assert ctx_value_text == doc_1_content
    assert ctx_value_bytes == doc_bytes_content
    assert ctx_value_metadata["title"] == doc_bytes_metadata["title"]
    assert ctx_value_path == doc_bytes_path

    with pytest.raises(InvalidContextBindException, match=r"^Cannot pull from an output-only bind.*?"):
        ctx_bind_err = ContextBind(
            binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
            context_bind_type=ContextBindType.model_output,
        )
        ctx_value_err = binder.pull_context(ctx_bind_err)

    with pytest.raises(InvalidContextBindException, match=r"^File not found for document.*?"):
        ctx_value_err = binder.pull_context(ContextBind(
            binded_id=f"{domain_1}.{doc_empty_id}",
            context_bind_type=ContextBindType.model,
        ))

    binder.push_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=ctx_id,
        context_bind_type=ContextBindType.model,
    ), doc_1_content_changed)
    assert binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=ctx_id,
        context_bind_type=ContextBindType.model,
    )) == doc_1_content_changed

    binder.push_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=ctx_id,
        context_bind_type=ContextBindType.text,
    ), doc_1_content_changed)
    assert binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=ctx_id,
        context_bind_type=ContextBindType.text,
    )) == doc_1_content_changed

    binder.push_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        context=ctx_id,
        context_bind_type=ContextBindType.bytes,
    ), doc_bytes_content_changed)
    assert binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        context=ctx_id,
        context_bind_type=ContextBindType.bytes,
    )) == doc_bytes_content_changed

    binder.push_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        context=ctx_id,
        context_bind_type=ContextBindType.document_metadata,
    ), doc_bytes_metadata_changed)
    assert binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        context=ctx_id,
        context_bind_type=ContextBindType.document_metadata,
    ))["title"] == doc_bytes_metadata_changed["title"]

    with pytest.raises(InvalidContextBindException, match=r"^Wrong metadata type.*?$"):
        binder.push_context(ContextBind(
            binded_id=f"{domain_1}.{doc_bytes_id}",
            context=ctx_id,
            context_bind_type=ContextBindType.document_metadata,
        ), tmp_path)

    @binder.resource()
    def factory_1(selector): return f"<{selector}>"

    with pytest.raises(InvalidResourceException, match=r"^Resource factory '.*?' is already registered, use 'force=True' to overwrite$"):
        @binder.resource(name="factory_1")
        def factory_error_1(selector): ...

    with pytest.raises(InvalidResourceException, match=r"^Resource factory '.*?' has not a compatible signature$"):
        @binder.resource()
        def factory_error_2(): ...

    assert binder.load_resource(ResourceBind(
        factory_name="factory_1",
        selector="test"
    )) == "<test>"



