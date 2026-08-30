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
    """Manager for context resolution, document state synchronization, and resource loading.

    The class operates with two levels of context:

    * **Shared context**: Acts as the pre-existing knowledge base; it is read by all
      operations but modified only by memory persistence operations.
    * **Local context**: Restricted to the specific operation; its documents are copies
      extracted from the shared context that store the operation's states and results.

    Thus, the Binder is responsible for:

    * Maintaining shared contexts and creating local contexts for operations when
      necessary.
    * Automatically resolving shared and local documents, copying them from the shared
      context when required.

    Additionally, Binder maintains resource factories to enable isolation during
    resource resolution. When a factory is not found in the local registry, Binder
    resolves the resource using the global registry.

    :param local_context_path: Optional path to local job context folders.
    :type local_context_path: pathlib.Path | None
    """

    _shared_context: dict[str, DocumentContext] | None = None
    _local_context: dict[str, DocumentContext] | None = None
    _factories: dict[str, Callable] | None = None
    _locks: dict[str, asyncio.Lock] | None = None

    def __init__(self, local_context_path: Path | None = None):
        self.local_context_path: Path | None = local_context_path

    @property
    def shared_context(self) -> dict[str, DocumentContext]:
        if self._shared_context is None:
            self._shared_context = {}
        return self._shared_context

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

    async def resolve_local_context(self, local_context_id: str) -> DocumentContext:
        """Load or create the local `DocumentContext` for an operation, caching it.

        :param local_context_id: Identifier of the local context (usually a job ID).
        :type local_context_id: str
        :returns: The loaded or newly created local `DocumentContext`.
        :rtype: DocumentContext
        :raises ContextBindingError: If `local_context_path` was not set on this Binder.
        """

        if not self.local_context_path:
            raise ContextBindingError("Cannot load local context, path is not defined")

        async with self._get_lock(local_context_id):
            if local_context_id in self.local_context:
                return self.local_context[local_context_id]

            settings_path = (
                self.local_context_path / local_context_id / "datorum.context.yml"
            )
            local_context: DocumentContext

            if settings_path.exists():
                local_context = DocumentContext.load(settings_path=settings_path)
            else:
                settings_path.parent.mkdir(exist_ok=True, parents=True)
                local_context = DocumentContext(id=local_context_id)
                local_context.save_as(settings_path=settings_path)

            self.local_context[local_context_id] = local_context
            return local_context

    async def resolve_local_document(
        self, shared_document_id: str, shared_context_id: str, local_context_id: str
    ) -> DocumentReference:
        """Get or create the local copy of a shared document within a local context.

        If the document doesn't already exist in the local context, it's created and
        its content is copied over from the shared document.

        :param shared_document_id: ID of the source document in the shared context.
        :type shared_document_id: str
        :param shared_context_id: ID of the shared context holding the source document.
        :type shared_context_id: str
        :param local_context_id: Identifier of the local context to resolve into.
        :type local_context_id: str
        :returns: The local `DocumentReference`.
        :rtype: DocumentReference
        :raises ContextBindingError: If the shared document doesn't exist.
        """

        local_context: DocumentContext = await self.resolve_local_context(
            local_context_id
        )
        local_document_id = f"{shared_context_id}.{shared_document_id}"

        async with self._get_lock(f"{local_context_id}:{local_document_id}"):
            local_document = local_context.get_document(id=local_document_id)

            if not local_document:
                shared_document = self.shared_context[shared_context_id].get_document(
                    id=shared_document_id
                )

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

    def add_context(self, context: DocumentContext) -> DocumentContext:
        """Register a `DocumentContext` as one of this Binder's shared contexts.

        :param context: Context to register, keyed by its `id`.
        :type context: DocumentContext
        :returns: The registered `context`, for chaining.
        :rtype: DocumentContext
        """

        self.shared_context[context.id] = context
        return context

    def resource(self, name: str | None = None, force: bool = False):
        """Decorator registering a function as a resource factory on this Binder.

        Factories registered here are checked before falling back to the global
        registry, allowing an operation to override a resource resolution locally.

        :param name: Factory name override, defaults to the function's own name.
        :type name: str | None, optional
        :param force: Overwrite an existing factory of the same name, defaults to False.
        :type force: bool, optional
        :raises ResourceBindingError: If already registered and `force` is False, or if
            the function's signature isn't a valid factory signature.
        """

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
        """Find the shared context that knows about a given domain.

        :param domain: Dotted domain name to search for.
        :type domain: str
        :param context: Context ID, list of context IDs to search, or None to search
            every registered shared context, defaults to None.
        :type context: str | list[str] | None, optional
        :returns: The first shared context that knows the domain.
        :rtype: DocumentContext
        :raises ContextBindingError: If a named context is unknown, or no candidate
            context knows the domain.
        """

        if isinstance(context, str):
            if context not in self.shared_context:
                raise ContextBindingError(f"Unknown context '{context}'")
            if not self.shared_context[context].knows_domain(domain):
                raise ContextBindingError(
                    f"Unknown domain '{domain}' in context '{context}'"
                )
            return self.shared_context[context]

        context_list: list[str] = context or list(self.shared_context.keys())
        for ctx_id in context_list:
            if ctx_id not in self.shared_context:
                continue
            if self.shared_context[ctx_id].knows_domain(domain):
                return self.shared_context[ctx_id]

        raise ContextBindingError(
            f"Unknown domain '{domain}' in context '{context or 'all'}'"
        )

    async def find_document(
        self,
        document_id: str,
        context: str | list[str] | None = None,
        local_context_id: str | None = None,
    ) -> DocumentReference:
        """Find a document by ID, optionally resolving its local-context copy.

        :param document_id: Document identifier to search for.
        :type document_id: str
        :param context: Context ID, list of context IDs to search, or None to search
            every registered shared context, defaults to None.
        :type context: str | list[str] | None, optional
        :param local_context_id: When set, resolve and return the local copy of the
            found document instead of the shared one, defaults to None.
        :type local_context_id: str | None, optional
        :returns: The found (or local-resolved) `DocumentReference`.
        :rtype: DocumentReference
        :raises ContextBindingError: If a named context is unknown, or the document
            isn't found in any candidate context.
        """

        document: DocumentReference | None = None

        if isinstance(context, str):
            if context not in self.shared_context:
                raise ContextBindingError(f"Unknown context '{context}'")

            if local_context_id:
                document = await self.resolve_local_document(
                    shared_document_id=document_id,
                    shared_context_id=context,
                    local_context_id=local_context_id,
                )

            else:
                document = self.shared_context[context].get_document(id=document_id)

        else:
            context_list: list[str] = context or list(self.shared_context.keys())
            for ctx_id in context_list:
                if ctx_id not in self.shared_context:
                    continue

                document = self.shared_context[ctx_id].get_document(id=document_id)
                if document:
                    if local_context_id:
                        document = await self.resolve_local_document(
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

    async def pull_context(
        self,
        bind: ContextBind,
        local_context_id: str | None = None,
    ) -> Any:
        """Resolve a context binding for reading, per its `ContextBindType`.

        Depending on `bind.context_bind_type`, returns a deserialized model instance,
        raw text, raw bytes, a metadata dict, or a filesystem path.

        :param bind: Context binding to resolve. Must allow input access.
        :type bind: ContextBind
        :param local_context_id: Local context to resolve into, required when
            `bind.local` is True, defaults to None.
        :type local_context_id: str | None, optional
        :returns: The resolved value, typed per the binding's `context_bind_type`.
        :rtype: Any
        :raises ContextBindingError: If the binding is local but no `local_context_id`
            is given, the binding doesn't allow input access, or the target file is
            missing for a mode that requires it.
        """

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

            if bind.local and local_context_id:
                context = await self.resolve_local_context(local_context_id)
                domain_id = f"{domain_context}.{domain_id}"
            else:
                context = self.find_domain_context(
                    domain=domain_id,
                    context=domain_context,
                )

            if bind.context_bind_type.is_metadata():
                return context.get_domain_metadata(domain=domain_id)
            return context.get_domain_path(domain=domain_id)

        document = await self.find_document(
            document_id=bind.binded_id,
            context=bind.context,
            local_context_id=local_context_id if bind.local else None,
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

    async def push_context(
        self,
        bind: ContextBind,
        value: Any,
        local_context_id: str | None = None,
    ):
        """Resolve a context binding for writing, per its `ContextBindType`.

        Depending on `bind.context_bind_type`, persists `value` as a serialized model,
        raw text, raw bytes, or domain/document metadata, updating the underlying
        document or context settings on disk.

        :param bind: Context binding to resolve. Must allow output access.
        :type bind: ContextBind
        :param value: Value to write; its expected type depends on the binding's
            `context_bind_type` (e.g. a `dict` for metadata modes).
        :type value: Any
        :param local_context_id: Local context to resolve into, required when
            `bind.local` is True, defaults to None.
        :type local_context_id: str | None, optional
        :raises ContextBindingError: If the binding is local but no `local_context_id`
            is given, the binding doesn't allow output access, or `value` isn't a
            `dict` for a metadata mode.
        """

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
            context = self.find_domain_context(domain_id, bind.context)

            if bind.local and local_context_id:
                domain_context = context.id
                context = await self.resolve_local_context(local_context_id)
                domain_id = f"{domain_context}.{domain_id}"

            context.set_domain_metadata(domain=domain_id, metadata=value)
            context.persistent.save()

        elif bind.context_bind_type.is_metadata():
            if not isinstance(value, dict):
                raise ContextBindingError(f"Wrong metadata type: '{type(value)}'")

            document: DocumentReference = await self.find_document(
                document_id=bind.binded_id, context=bind.context
            )
            if bind.local and local_context_id:
                document = await self.resolve_local_document(
                    shared_document_id=document.id,
                    shared_context_id=document.context.id,
                    local_context_id=local_context_id,
                )

            document.metadata = value
            document.persistent.save()

        else:
            document = await self.find_document(
                document_id=bind.binded_id, context=bind.context
            )
            if bind.local and local_context_id:
                document = await self.resolve_local_document(
                    shared_document_id=document.id,
                    shared_context_id=document.context.id,
                    local_context_id=local_context_id,
                )

            if bind.context_bind_type.is_model():
                document.save(value)
            elif bind.context_bind_type.is_text():
                document.doc_path.write_text(str(value), encoding="utf-8")
            elif bind.context_bind_type.is_bytes():
                document.doc_path.write_bytes(bytes(value))

    def load_resource(self, bind: ResourceBind) -> Any:
        """Resolve a resource binding by calling its factory with the bind's selector.

        Looks up `bind.factory_name` in this Binder's local factories first, falling
        back to the global resource factory registry.

        :param bind: Resource binding to resolve.
        :type bind: ResourceBind
        :returns: The value produced by the resolved factory.
        :rtype: Any
        :raises ResourceFactoryError: If the factory name isn't registered anywhere.
        """

        factory: Callable = (
            self.factories[bind.factory_name]
            if bind.factory_name in self.factories
            else get_resource_factory(bind.factory_name)
        )
        return factory(bind.selector)
