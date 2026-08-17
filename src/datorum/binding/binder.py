import inspect
from pathlib import Path
import types
from typing import (
    Any,
    Callable,
    Optional,
    Union,
    get_type_hints,
    get_origin,
    get_args,
)

from ..context.settings import (
    DocumentReference,
    DocumentContext,
)
from .exceptions import (
    ResourceBindingError,
    ContextBindingError,
)
from .registry import (
    validate_factory_signature,
    get_resource_factory,
)


class Binder:

    _contexts: Optional[dict[str, DocumentContext]] = None
    _factories: Optional[dict[str, Callable]] = None

    @property
    def contexts(self) -> dict[str, DocumentContext]:
        if self._contexts is None:
            self._contexts = {}
        return self._contexts

    @property
    def factories(self) -> dict[str, Callable]:
        if self._factories is None:
            self._factories = {}
        return self._factories

    def add_context(self, context: DocumentContext) -> DocumentContext:
        context = DocumentContext.load(
            settings_path=settings_path)
        if base_path is not None:
            context.base_path = base_path
        self.contexts[context.id] = context
        return context

    def resource(self, name: str | None = None, force: bool = False):
        def decorator(func):
            factory_name = name or func.__name__
            if factory_name in self.factories and not force:
                raise ResourceBindingError(
                    f"Resource factory '{factory_name}' is already registered, use 'force=True' to overwrite")
            if not validate_factory_signature(func):
                raise ResourceBindingError(
                    f"Resource factory '{factory_name}' has not a compatible signature")
            self.factories[factory_name] = func
            return func
        return decorator

    def find_domain_context(
        self,
        domain: str,
        context: str | list[str] | None = None,
    ) -> DocumentContext:
        domain_context: Optional[DocumentContext] = None

        if isinstance(context, str):
            if context not in self.contexts:
                raise ContextBindingError(
                    f"Unknown context '{context}'")
            if not self.contexts[context].knows_domain(domain):
                raise ContextBindingError(
                    f"Unknown domain '{domain}' in context '{context}'")
            return self.contexts[context]

        context_list: list[str] = context or self.contexts.keys()
        for ctx_id in context_list:
            if ctx_id not in self.contexts:
                continue
            if self.contexts[ctx_id].knows_domain(domain):
                return self.contexts[ctx_id]

        raise ContextBindingError(
            f"Unknown domain '{domain}' in context '{context or 'all'}'")

    def find_document(
        self,
        document_id: str,
        context: str | list[str] | None = None,
    ) -> DocumentReference:
        document: Optional[DocumentReference] = None

        if isinstance(context, str):
            if context not in self.contexts:
                raise ContextBindingError(
                    f"Unknown context '{context}'")
            document = self.contexts[context].get_document(
                id=document_id)

        else:
            context_list: list[str] = context or self.contexts.keys()
            for ctx_id in context_list:
                if ctx_id not in self.contexts:
                    continue
                document = self.contexts[ctx_id].get_document(
                    id=document_id)
                if document:
                    break

        if not document:
            raise ContextBindingError(
                f"Unknown document '{document_id}' in context '{context or 'all'}'")

        return document

    def pull_context(self, bind: ContextBind) -> Any:
        if not bind.context_bind_type.is_input():
            raise ContextBindingError(
                f"Cannot pull from an output-only bind ('{str(bind.binded_id)}')")

        if bind.context_bind_type.is_domain():
            context = self.find_domain_context(
                domain=bind.binded_id, context=bind.context)

            if bind.context_bind_type.is_metadata():
                return context.get_domain_metadata(domain=bind.binded_id)
            return context.get_domain_path(domain=bind.binded_id)

        document = self.find_document(
            document_id=bind.binded_id, context=bind.context)

        if bind.context_bind_type.is_io() and not document.doc_path.exists():
            raise ContextBindingError(
                f"File not found for document '{bind.binded_id}' (path: '{document.doc_path}')")

        if bind.context_bind_type.is_model():
            return document.load()
        if bind.context_bind_type.is_text():
            return document.doc_path.read_text(encoding="utf-8")
        if bind.context_bind_type.is_bytes():
            return document.doc_path.read_bytes()
        if bind.context_bind_type.is_metadata():
            return document.metadata
        return document.doc_path

    def push_context(self, bind: ContextBind, value: Any):
        if not bind.context_bind_type.is_output():
            raise ContextBindingError(
                f"Cannot push to an input-only bind ('{str(bind.binded_id)}')")

        if bind.context_bind_type.is_domain():
            if not isinstance(value, dict):
                raise ContextBindingError(
                    f"Wrong metadata type: '{type(value)}'")
            context = self.find_domain_context(
                domain=bind.binded_id, context=bind.context)
            context.set_domain_metadata(
                domain=bind.binded_id, metadata=value)
            context.persistent.save()

        elif bind.context_bind_type.is_metadata():
            if not isinstance(value, dict):
                raise ContextBindingError(
                    f"Wrong metadata type: '{type(value)}'")
            document = self.find_document(
                document_id=bind.binded_id, context=bind.context)
            document.metadata = value
            document.persistent.save()

        else:
            document = self.find_document(
                document_id=bind.binded_id, context=bind.context)

            if bind.context_bind_type.is_model():
                document.save(value)
            elif bind.context_bind_type.is_text():
                document.doc_path.write_text(str(value), encoding="utf-8")
            elif bind.context_bind_type.is_bytes():
                document.doc_path.write_bytes(bytes(value))

    def load_resource(self, bind: ResourceBind) -> Any:
        factory: Callable = self.factories[bind.factory_name] \
            if bind.factory_name in self.factories \
                else get_resource_factory(bind.factory_name)
        return factory(bind.selector)

