from pathlib import Path

import pytest

from datorum.context.registry import (
    register_doc_type,
    register_doc_model,
    serializer, deserializer,
)
from datorum.context.settings import (
    DocumentReference,
    DocumentContext,
)
from datorum.binding.settings import (
    ContextBindType,
    ContextBind, ResourceBind,
)
from datorum.binding.registry import (
    validate_factory_signature,
    resource, get_resource_factory,
)
from datorum.binding.binder import (
    Binder,
)
from datorum.binding.exceptions import (
    ResourceBindingError,
    ContextBindingError,
)


# ==============================================================================
# Shared-context bindings (find_document / pull_context / push_context /
# find_domain_context / resource loading), ported to the async Binder API.
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.depends(on=[
    "tests/test_context_registry.py",
    "tests/test_context_settings.py",
])
async def test_binder(tmp_path: Path):
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

    register_doc_type("bin", extensions=["bin"])
    register_doc_model("bin", clazz=bytes, default_doc_type="bin")
    @serializer(doc_type="bin", doc_model="bin")
    def bytes_serializer(data: bytes, file_path: Path):
        file_path.write_bytes(data)
    @deserializer(doc_type="bin", doc_model="bin")
    def bytes_deserializer(file_path: Path) -> bytes:
        return file_path.read_bytes()

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
    context: DocumentContext = DocumentContext.load(tmp_path / f"{ctx_id}.yml")
    context.base_path = tmp_path
    binder.add_context(context)

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

    with pytest.raises(ContextBindingError, match=r"^Unknown context.*?"):
        binder.find_domain_context(domain=domain_1, context="invalid")
    with pytest.raises(ContextBindingError, match=r"^Unknown domain.*?"):
        binder.find_domain_context(domain="invalid", context=ctx_id)
    with pytest.raises(ContextBindingError, match=r"^Unknown domain.*?"):
        binder.find_domain_context(domain=domain_2)

    domain_1_path = await binder.pull_context(ContextBind(
        binded_id=domain_1, field_id="domain_path",
        context_bind_type=ContextBindType.domain_path
    ))
    domain_1_metadata_1 = await binder.pull_context(ContextBind(
        binded_id=domain_1, field_id="domain_metadata",
        context_bind_type=ContextBindType.domain_metadata
    ))

    assert domain_1_path == tmp_path / domain_1
    assert domain_1_metadata_1["title"] == domain_1_metadata["title"]

    await binder.push_context(ContextBind(
        binded_id=domain_1, field_id="domain_metadata",
        context_bind_type=ContextBindType.domain_metadata
    ), domain_1_metadata_changed)

    assert (await binder.pull_context(ContextBind(
        binded_id=domain_1, field_id="domain_metadata",
        context_bind_type=ContextBindType.domain_metadata
    )))["title"] == domain_1_metadata_changed["title"]

    with pytest.raises(ContextBindingError, match=r"^Cannot push to an input-only bind.*?"):
        await binder.push_context(ContextBind(
            binded_id=domain_1, field_id="domain_path",
            context_bind_type=ContextBindType.domain_path
        ), tmp_path)
    with pytest.raises(ContextBindingError, match=r"^Wrong metadata type.*?"):
        await binder.push_context(ContextBind(
            binded_id=domain_1, field_id="domain_metadata",
            context_bind_type=ContextBindType.domain_metadata
        ), tmp_path)

    doc_2 = await binder.find_document(
        document_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=ctx_id,
    )
    doc_3 = await binder.find_document(
        document_id=f"{domain_1}.{domain_2}.{doc_1_id}",
    )
    doc_4 = await binder.find_document(
        document_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        context=["invalid", ctx_id],
    )

    assert doc_2.id == doc_1.id
    assert doc_2.doc_path == doc_1.doc_path
    assert doc_3.id == doc_1.id
    assert doc_3.doc_path == doc_1.doc_path
    assert doc_4.id == doc_1.id
    assert doc_4.doc_path == doc_1.doc_path

    with pytest.raises(ContextBindingError, match=r"^Unknown context.*?"):
        await binder.find_document(document_id=doc_1_id, context="invalid")

    with pytest.raises(ContextBindingError, match=r"^Unknown document.*?"):
        await binder.find_document(document_id="invalid")

    ctx_value_1 = await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        field_id="doc_model", context=ctx_id,
        context_bind_type=ContextBindType.model,
    ))
    ctx_value_2 = await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        field_id="doc_model", context=["invalid", ctx_id],
        context_bind_type=ContextBindType.model,
    ))
    ctx_value_3 = await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        field_id="doc_model",
        context_bind_type=ContextBindType.model,
    ))
    ctx_value_text = await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        field_id="doc_text",
        context_bind_type=ContextBindType.text,
    ))
    ctx_value_bytes = await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        field_id="doc_bytes",
        context_bind_type=ContextBindType.bytes,
    ))
    ctx_value_metadata = await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        field_id="doc_metadata",
        context_bind_type=ContextBindType.document_metadata,
    ))
    ctx_value_path = await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        field_id="doc_path",
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

    with pytest.raises(ContextBindingError, match=r"^Cannot pull from an output-only bind.*?"):
        ctx_bind_err = ContextBind(
            binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
            field_id="doc_model",
            context_bind_type=ContextBindType.model_output,
        )
        await binder.pull_context(ctx_bind_err)

    with pytest.raises(ContextBindingError, match=r"^File not found for document.*?"):
        await binder.pull_context(ContextBind(
            binded_id=f"{domain_1}.{doc_empty_id}",
            field_id="doc_model",
            context_bind_type=ContextBindType.model,
        ))

    await binder.push_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        field_id="doc_model", context=ctx_id,
        context_bind_type=ContextBindType.model,
    ), doc_1_content_changed)
    assert (await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        field_id="doc_model", context=ctx_id,
        context_bind_type=ContextBindType.model,
    ))) == doc_1_content_changed

    await binder.push_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        field_id="doc_text", context=ctx_id,
        context_bind_type=ContextBindType.text,
    ), doc_1_content_changed)
    assert (await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{domain_2}.{doc_1_id}",
        field_id="doc_text", context=ctx_id,
        context_bind_type=ContextBindType.text,
    ))) == doc_1_content_changed

    await binder.push_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        field_id="doc_bytes", context=ctx_id,
        context_bind_type=ContextBindType.bytes,
    ), doc_bytes_content_changed)
    assert (await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        field_id="doc_bytes", context=ctx_id,
        context_bind_type=ContextBindType.bytes,
    ))) == doc_bytes_content_changed

    await binder.push_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        field_id="doc_metadata", context=ctx_id,
        context_bind_type=ContextBindType.document_metadata,
    ), doc_bytes_metadata_changed)
    assert (await binder.pull_context(ContextBind(
        binded_id=f"{domain_1}.{doc_bytes_id}",
        field_id="doc_metadata", context=ctx_id,
        context_bind_type=ContextBindType.document_metadata,
    )))["title"] == doc_bytes_metadata_changed["title"]

    with pytest.raises(ContextBindingError, match=r"^Wrong metadata type.*?$"):
        await binder.push_context(ContextBind(
            binded_id=f"{domain_1}.{doc_bytes_id}",
            field_id="doc_metadata", context=ctx_id,
            context_bind_type=ContextBindType.document_metadata,
        ), tmp_path)

    @binder.resource()
    def factory_1(selector): return f"<{selector}>"

    with pytest.raises(ResourceBindingError, match=r"^Resource factory '.*?' is already registered, use 'force=True' to overwrite$"):
        @binder.resource(name="factory_1")
        def factory_error_1(selector): ...

    with pytest.raises(ResourceBindingError, match=r"^Resource factory '.*?' has not a compatible signature$"):
        @binder.resource()
        def factory_error_2(): ...

    assert binder.load_resource(ResourceBind(
        field_id="resoure_field",
        factory_name="factory_1",
        selector="test"
    )) == "<test>"


# ==============================================================================
# Fixtures for local/shared binding coverage
# ==============================================================================

@pytest.fixture
def shared_ctx_and_binder(tmp_path: Path):
    """A Binder tied to one shared context ('ctx1') holding one text
    document ('domain.doc'), plus a local_context_path for materializing
    local copies."""
    ctx_id = "ctx1"
    doc_id = "domain.doc"
    doc = DocumentReference(id=doc_id)
    ctx = DocumentContext(id=ctx_id, documents={doc_id: doc})
    ctx.save_as(tmp_path / "shared" / f"{ctx_id}.yml")
    ctx.base_path = tmp_path / "shared"
    doc.save("shared content")

    local_path = tmp_path / "local"
    binder = Binder(local_context_path=local_path)
    binder.add_context(ctx)

    return binder, ctx, doc, local_path


# ==============================================================================
# resolve_local_context
# ==============================================================================

@pytest.mark.asyncio
async def test_resolve_local_context_requires_local_context_path():
    binder = Binder()  # no local_context_path
    with pytest.raises(ContextBindingError, match=r"^Cannot load local context.*?"):
        await binder.resolve_local_context("flow_1")


@pytest.mark.asyncio
async def test_resolve_local_context_creates_and_caches(tmp_path: Path):
    binder = Binder(local_context_path=tmp_path / "local")

    ctx1 = await binder.resolve_local_context("flow_1")
    settings_file = tmp_path / "local" / "flow_1" / "datorum.context.yml"
    assert settings_file.exists()

    # Second call for the same id returns the exact same cached instance,
    # not a fresh load from disk.
    ctx1_again = await binder.resolve_local_context("flow_1")
    assert ctx1_again is ctx1

    # A different id gets its own, separate context/directory.
    ctx2 = await binder.resolve_local_context("flow_2")
    assert ctx2 is not ctx1
    assert (tmp_path / "local" / "flow_2" / "datorum.context.yml").exists()


@pytest.mark.asyncio
async def test_resolve_local_context_loads_existing_from_disk(tmp_path: Path):
    local_path = tmp_path / "local"

    binder_1 = Binder(local_context_path=local_path)
    ctx = await binder_1.resolve_local_context("flow_1")
    ctx.domain_metadata["marker"] = {"from": "first binder"}
    ctx.save()

    # A brand new Binder instance pointed at the same local_context_path
    # must load the persisted context from disk rather than create a new,
    # empty one.
    binder_2 = Binder(local_context_path=local_path)
    reloaded = await binder_2.resolve_local_context("flow_1")
    assert reloaded.domain_metadata["marker"]["from"] == "first binder"


# ==============================================================================
# resolve_local_document
# ==============================================================================

@pytest.mark.asyncio
async def test_resolve_local_document_materializes_a_copy(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    local_doc = await binder.resolve_local_document(
        shared_document_id=doc.id,
        shared_context_id=ctx.id,
        local_context_id="flow_1",
    )

    assert local_doc.id == f"{ctx.id}.{doc.id}"
    assert local_doc.doc_path != doc.doc_path
    assert local_doc.doc_path.read_text(encoding="utf-8") == "shared content"


@pytest.mark.asyncio
async def test_resolve_local_document_caches_same_copy_across_calls(shared_ctx_and_binder):
    """Every subsequent reference to the same document id under the same
    local_context_id resolves to the same cached copy -- this is what keeps
    a local binding (e.g. a chat history) coherent across every step of one
    flow."""
    binder, ctx, doc, local_path = shared_ctx_and_binder

    first = await binder.resolve_local_document(
        shared_document_id=doc.id, shared_context_id=ctx.id, local_context_id="flow_1",
    )
    first.doc_path.write_text("mutated by step 1", encoding="utf-8")

    second = await binder.resolve_local_document(
        shared_document_id=doc.id, shared_context_id=ctx.id, local_context_id="flow_1",
    )

    assert second is first
    # The mutation from the first reference is visible to the second --
    # it was not re-copied from the (unmutated) shared source.
    assert second.doc_path.read_text(encoding="utf-8") == "mutated by step 1"


@pytest.mark.asyncio
async def test_resolve_local_document_isolated_by_local_context_id(shared_ctx_and_binder):
    """Two different operations (local_context_id) working on the same
    shared document each get their own, independent local copy."""
    binder, ctx, doc, local_path = shared_ctx_and_binder

    doc_a = await binder.resolve_local_document(
        shared_document_id=doc.id, shared_context_id=ctx.id, local_context_id="flow_a",
    )
    doc_b = await binder.resolve_local_document(
        shared_document_id=doc.id, shared_context_id=ctx.id, local_context_id="flow_b",
    )

    assert doc_a is not doc_b
    assert doc_a.doc_path != doc_b.doc_path

    doc_a.doc_path.write_text("mutated in flow_a", encoding="utf-8")
    assert doc_b.doc_path.read_text(encoding="utf-8") == "shared content"


@pytest.mark.asyncio
async def test_resolve_local_document_does_not_leak_mutations_to_shared_source(shared_ctx_and_binder):
    """The core guarantee from the design: mutating a local binding must
    never corrupt the shared document used to seed it."""
    binder, ctx, doc, local_path = shared_ctx_and_binder

    local_doc = await binder.resolve_local_document(
        shared_document_id=doc.id, shared_context_id=ctx.id, local_context_id="flow_1",
    )
    local_doc.doc_path.write_text("mutated locally", encoding="utf-8")

    assert doc.doc_path.read_text(encoding="utf-8") == "shared content"


@pytest.mark.asyncio
async def test_resolve_local_document_unknown_shared_document_raises(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    with pytest.raises(ContextBindingError, match=r"^Unknown document.*?"):
        await binder.resolve_local_document(
            shared_document_id="does.not.exist",
            shared_context_id=ctx.id,
            local_context_id="flow_1",
        )


# ==============================================================================
# find_document with local_context_id
# ==============================================================================

@pytest.mark.asyncio
async def test_find_document_local_context_id_with_explicit_context(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    local_doc = await binder.find_document(
        document_id=doc.id, context=ctx.id, local_context_id="flow_1",
    )
    assert local_doc.id == f"{ctx.id}.{doc.id}"
    assert local_doc.doc_path != doc.doc_path


@pytest.mark.asyncio
async def test_find_document_local_context_id_without_explicit_context(shared_ctx_and_binder):
    """When no context is given, find_document searches all shared contexts
    for the document, then materializes the local copy against the context
    it was actually found in."""
    binder, ctx, doc, local_path = shared_ctx_and_binder

    local_doc = await binder.find_document(
        document_id=doc.id, local_context_id="flow_1",
    )
    assert local_doc.id == f"{ctx.id}.{doc.id}"
    assert local_doc.doc_path != doc.doc_path


# ==============================================================================
# pull_context / push_context: local=True requires a local_context_id
# ==============================================================================

@pytest.mark.asyncio
async def test_pull_context_local_bind_without_local_context_id_raises(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    with pytest.raises(ContextBindingError, match=r"^Local context not defined.*?"):
        await binder.pull_context(ContextBind(
            field_id="doc", binded_id=doc.id, context=ctx.id,
            context_bind_type=ContextBindType.model,
            local=True,
        ))


@pytest.mark.asyncio
async def test_push_context_local_bind_without_local_context_id_raises(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    with pytest.raises(ContextBindingError, match=r"^Local context not defined.*?"):
        await binder.push_context(
            ContextBind(
                field_id="doc", binded_id=doc.id, context=ctx.id,
                context_bind_type=ContextBindType.model,
                local=True,
            ),
            "new value",
        )


# ==============================================================================
# pull_context / push_context: local bindings, coherence and isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_local_binding_pull_and_push_are_coherent_across_the_same_flow(shared_ctx_and_binder):
    """Simulates several steps of one pipeline flow (same local_context_id)
    sharing one local chat-history-like binding: a push from one step must
    be visible to a pull from the next."""
    binder, ctx, doc, local_path = shared_ctx_and_binder

    bind = ContextBind(
        field_id="doc", binded_id=doc.id, context=ctx.id,
        context_bind_type=ContextBindType.model,
        local=True,
    )

    initial = await binder.pull_context(bind, local_context_id="flow_1")
    assert initial == "shared content"

    await binder.push_context(bind, "updated by step 1", local_context_id="flow_1")

    updated = await binder.pull_context(bind, local_context_id="flow_1")
    assert updated == "updated by step 1"

    # The shared source document was never touched.
    assert doc.doc_path.read_text(encoding="utf-8") == "shared content"


@pytest.mark.asyncio
async def test_local_binding_isolated_from_a_different_flow(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    bind = ContextBind(
        field_id="doc", binded_id=doc.id, context=ctx.id,
        context_bind_type=ContextBindType.model,
        local=True,
    )

    await binder.push_context(bind, "mutated in flow_1", local_context_id="flow_1")
    other_flow_value = await binder.pull_context(bind, local_context_id="flow_2")

    assert other_flow_value == "shared content"


@pytest.mark.asyncio
async def test_local_binding_text_and_bytes_push_pull(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    text_bind = ContextBind(
        field_id="doc", binded_id=doc.id, context=ctx.id,
        context_bind_type=ContextBindType.text, local=True,
    )
    await binder.push_context(text_bind, "local text value", local_context_id="flow_1")
    assert await binder.pull_context(text_bind, local_context_id="flow_1") == "local text value"
    assert doc.doc_path.read_text(encoding="utf-8") == "shared content"


@pytest.mark.asyncio
async def test_local_binding_metadata_push_pull(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    meta_bind = ContextBind(
        field_id="doc", binded_id=doc.id, context=ctx.id,
        context_bind_type=ContextBindType.document_metadata, local=True,
    )
    await binder.push_context(meta_bind, {"title": "Local Title"}, local_context_id="flow_1")
    pulled = await binder.pull_context(meta_bind, local_context_id="flow_1")

    assert pulled["title"] == "Local Title"
    assert doc.metadata == {}  # shared document's metadata is untouched


# ==============================================================================
# local domain bindings (domain-path / domain-metadata, local=True)
# ==============================================================================

@pytest.mark.asyncio
async def test_local_domain_metadata_push_pull_is_scoped_under_the_source_context(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    domain_bind = ContextBind(
        field_id="domain_meta", binded_id="domain",
        context=ctx.id,
        context_bind_type=ContextBindType.domain_metadata,
        local=True,
    )

    await binder.push_context(domain_bind, {"title": "Local Domain"}, local_context_id="flow_1")
    pulled = await binder.pull_context(domain_bind, local_context_id="flow_1")
    assert pulled["title"] == "Local Domain"

    # Stored in the local context under "<source_context_id>.<domain>",
    # per the design -- the shared context's own domain metadata is untouched.
    local_context = await binder.resolve_local_context("flow_1")
    assert local_context.domain_metadata[f"{ctx.id}.domain"]["title"] == "Local Domain"
    assert "domain" not in ctx.domain_metadata


@pytest.mark.asyncio
async def test_local_domain_path_pull(shared_ctx_and_binder):
    binder, ctx, doc, local_path = shared_ctx_and_binder

    domain_bind = ContextBind(
        field_id="domain_path", binded_id="domain",
        context=ctx.id,
        context_bind_type=ContextBindType.domain_path,
        local=True,
    )
    path = await binder.pull_context(domain_bind, local_context_id="flow_1")

    local_context = await binder.resolve_local_context("flow_1")
    assert path == local_context.get_domain_path(f"{ctx.id}.domain")


# ==============================================================================
# locks
# ==============================================================================

def test_get_lock_is_reused_for_the_same_key():
    binder = Binder()
    lock_1 = binder._get_lock("flow_1")
    lock_2 = binder._get_lock("flow_1")
    lock_3 = binder._get_lock("flow_2")

    assert lock_1 is lock_2
    assert lock_1 is not lock_3