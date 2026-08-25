import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import (
    Any,
)

from ..context.settings import (
    DocumentContext,
    DocumentReference,
)
from .exceptions import (
    ContextBindingError,
    ResourceBindingError,
)
from .registry import (
    get_resource_factory,
    validate_factory_signature,
)
from .settings import ContextBind, ResourceBind


class Binder:
    _contexts: dict[str, DocumentContext] | None = None
    _local_context: dict[str, DocumentContext] | None = None
    _factories: dict[str, Callable] | None = None
    _locks: dict[str, asyncio.Lock] | None = None

    def __init__(self, local_context_path: Path | None = None):
        self.local_context_path: Path | None = local_context_path

    @property
    def contexts(self) -> dict[str, DocumentContext]:
        if self._contexts is None:
            self._contexts = {}
        return self._contexts

    @property
    def local_context(self) -> dict[str, DocumentContext]:
        if self._local_context is None:
            self._local_context = {}
        return self._local_context

    @property
    def factories(self) -> dict[str, Callable]:
        if self._factories is None:
            self._factories = {}
        return self._factories

    @property
    def locks(self) -> dict[str, asyncio.Lock]:
        if self._locks is None:
            self._locks = {}
        return self._locks

    def _get_lock(self, local_context_id: str) -> asyncio.Lock:
        return self.locks.setdefault(local_context_id, asyncio.Lock())

    async def _prepare_local_context(self, local_context_id: str) -> DocumentContext:
        if not self.local_context_path:
            raise ContextBindingError("Cannot load local context, path is not defined")

        async with self._get_lock(local_context_id):
            if local_context_id in self.local_context:
                return self.local_context[local_context_id]

            settings_path = self.local_context_path / local_context_id / "datorum.context.yml"
            local_context: DocumentContext

            if settings_path.exists():
                local_context = DocumentContext.load(settings_path=settings_path)
            else:
                settings_path.mkdir(exist_ok=True, parents=True)
                local_context = DocumentContext()
                local_context.save_as(settings_path=settings_path)

            self.local_context[local_context_id] = local_context
            return local_context

    async def _prepare_local_document(self, shared_document_id: str, shared_context_id: str, local_context_id: str) -> DocumentReference:
        local_context: DocumentContext = await self._prepare_local_context(local_context_id)
        local_document_id = f"{shared_context_id}.{shared_document_id}"

        async with self._get_lock(f"{local_context_id}:{local_document_id}"):
            local_document = local_context.get_document(id=local_document_id)

            if not local_document:
                shared_document = self.contexts[shared_context_id].get_document(id=shared_document_id)

                if not shared_document:
                    raise ContextBindingError(
                        f"Unknown document '{shared_document_id}' in context '{shared_context_id}'"
                    )

                local_document = local_context.create_document(
                    id=local_document_id,
                    doc_type=shared_document.doc_type,
                    doc_model=shared_document.doc_model,
                    extension=shared_document.extension,
                )
                shared_document.copy_to(target=local_document)

            return local_document

    async def add_context(self, context: DocumentContext) -> DocumentContext:
        self.contexts[context.id] = context
        return context

    def resource(self, name: str | None = None, force: bool = False):
        def decorator(func):
            factory_name = name or func.__name__
            if factory_name in self.factories and not force:
                raise ResourceBindingError(
                    f"Resource factory '{factory_name}' is already registered, use 'force=True' to overwrite"
                )
            if not validate_factory_signature(func):
                raise ResourceBindingError(
                    f"Resource factory '{factory_name}' has not a compatible signature"
                )
            self.factories[factory_name] = func
            return func

        return decorator

    def find_domain_context(
        self,
        domain: str,
        context: str | list[str] | None = None,
    ) -> DocumentContext:
        if isinstance(context, str):
            if context not in self.contexts:
                raise ContextBindingError(f"Unknown context '{context}'")
            if not self.contexts[context].knows_domain(domain):
                raise ContextBindingError(
                    f"Unknown domain '{domain}' in context '{context}'"
                )
            return self.contexts[context]

        context_list: list[str] = context or list(self.contexts.keys())
        for ctx_id in context_list:
            if ctx_id not in self.contexts:
                continue
            if self.contexts[ctx_id].knows_domain(domain):
                return self.contexts[ctx_id]

        raise ContextBindingError(
            f"Unknown domain '{domain}' in context '{context or 'all'}'"
        )

    async def find_document(
        self,
        document_id: str,
        context: str | list[str] | None = None,
        local_context_id: str | None = None,
    ) -> DocumentReference:
        document: DocumentReference | None = None

        if isinstance(context, str):
            if context not in self.contexts:
                raise ContextBindingError(f"Unknown context '{context}'")

            if local_context_id:
                document = await self._prepare_local_document(
                    shared_document_id=document_id,
                    shared_context_id=context,
                    local_context_id=local_context_id,
                )

            else:
                document = self.contexts[context].get_document(id=document_id)

        else:
            context_list: list[str] = context or list(self.contexts.keys())
            for ctx_id in context_list:
                if ctx_id not in self.contexts:
                    continue

                document = self.contexts[ctx_id].get_document(id=document_id)
                if document:
                    if local_context_id:
                        document = await self._prepare_local_document(
                            shared_document_id=document_id,
                            shared_context_id=ctx_id,
                            local_context_id=local_context_id,
                        )
                    break

        if not document:
            raise ContextBindingError(
                f"Unknown document '{document_id}' in context '{context or 'all'}'"
            )

        return document

    def pull_context(self,
        bind: ContextBind,
        local_context_id: str | None = None,
    ) -> Any:
        if bind.local and not local_context_id:
            raise ContextBindingError(
                f"Local context not defined for the local bind '{bind.binded_id!s}'"
            )
        if not bind.context_bind_type.is_input():
            raise ContextBindingError(
                f"Cannot pull from an output-only bind ('{bind.binded_id!s}')"
            )

        if bind.context_bind_type.is_domain():
            domain_id = bind.binded_id
            domain_context = bind.context

            if bind.local:
                context = await self._prepare_local_context(local_context_id)
                domain_id = f"{domain_context}.{domain_id}"
            else:
                context = self.find_domain_context(
                    domain=domain_id, context=domain_context,
                )

            if bind.context_bind_type.is_metadata():
                return context.get_domain_metadata(domain=domain_id)
            return context.get_domain_path(domain=domain_id)

        document = self.find_document(
            document_id=bind.binded_id,
            context=bind.context,
            local_context_id=local_context_id if bind.local else None
        )

        if bind.context_bind_type.is_io() and not document.doc_path.exists():
            raise ContextBindingError(
                f"File not found for document '{bind.binded_id}' (path: '{document.doc_path}')"
            )

        if bind.context_bind_type.is_model():
            return document.load()
        if bind.context_bind_type.is_text():
            return document.doc_path.read_text(encoding="utf-8")
        if bind.context_bind_type.is_bytes():
            return document.doc_path.read_bytes()
        if bind.context_bind_type.is_metadata():
            return document.metadata
        return document.doc_path

    def push_context(self,
        bind: ContextBind,
        value: Any,
        local_context_id: str | None = None,
    ):
        if bind.local and not local_context_id:
            raise ContextBindingError(
                f"Local context not defined for the local bind '{bind.binded_id!s}'"
            )
        if not bind.context_bind_type.is_output():
            raise ContextBindingError(
                f"Cannot push to an input-only bind ('{bind.binded_id!s}')"
            )

        if bind.context_bind_type.is_domain():
            if not isinstance(value, dict):
                raise ContextBindingError(f"Wrong metadata type: '{type(value)}'")

            domain_id = bind.binded_id
            domain_context = bind.context

            if bind.local:
                context = await self._prepare_local_context(local_context_id)
                domain_id = f"{domain_context}.{domain_id}"
            else:
                context = self.find_domain_context(
                    domain=domain_id, context=domain_context,
                )

            context.set_domain_metadata(domain=domain_id, metadata=value)
            context.persistent.save()

        elif bind.context_bind_type.is_metadata():
            if not isinstance(value, dict):
                raise ContextBindingError(f"Wrong metadata type: '{type(value)}'")
            document = self.find_document(
                document_id=bind.binded_id, context=bind.context
            )
            document.metadata = value
            document.persistent.save()

        else:
            document = self.find_document(
                document_id=bind.binded_id, context=bind.context
            )

            if bind.context_bind_type.is_model():
                document.save(value)
            elif bind.context_bind_type.is_text():
                document.doc_path.write_text(str(value), encoding="utf-8")
            elif bind.context_bind_type.is_bytes():
                document.doc_path.write_bytes(bytes(value))

    def load_resource(self, bind: ResourceBind) -> Any:
        factory: Callable = (
            self.factories[bind.factory_name]
            if bind.factory_name in self.factories
            else get_resource_factory(bind.factory_name)
        )
        return factory(bind.selector)
