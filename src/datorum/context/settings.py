import shutil
from pathlib import Path
from typing import Any

from pydantic import Field, PrivateAttr

from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings
from .exceptions import (
    DocumentReferenceError,
    DocumentReadingError,
    DocumentWritingError,
)
from .registry import (
    DocumentHandler,
    DocumentModel,
    DocumentType,
    get_doc_handler,
    get_doc_model,
    get_doc_type,
)


class DocumentReference(BaseDatorumSettings):
    """Reference pointing to a physical document on disk within a context."""

    id: str = Field(description="Unique document identifier within the context.")
    doc_type: str = Field(
        "text/plain", description="MIME content type, defaults to 'text/plain'."
    )
    doc_model: str = Field(
        "text", description="Document model type, defaults to 'text'."
    )
    extension: str | None = Field(None, description="Explicit file extension override.")

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def context(self) -> "DocumentContext":
        if isinstance(self.persistent, DocumentContext):
            return self.persistent
        raise DocumentReferenceError(f"Document out of context: '{self.id}'")
        
    @property
    def registry_doc_type(self) -> DocumentType:
        return get_doc_type(self.doc_type)

    @property
    def registry_doc_model(self) -> DocumentModel:
        return get_doc_model(self.doc_model)

    @property
    def registry_doc_handler(self) -> DocumentHandler:
        return get_doc_handler(doc_type=self.doc_type, doc_model=self.doc_model)

    @property
    def base_path(self) -> Path:
        if hasattr(self.persistent, "base_path") and self.persistent.base_path:
            return self.persistent.base_path
        return self.settings_path.parent

    @property
    def name(self) -> str:
        _, name, _ = self._decompose_id()
        return name

    @property
    def domain_list(self) -> list[str]:
        domain_list, _, _ = self._decompose_id()
        return domain_list

    @property
    def domain(self) -> str:
        return ".".join(self.domain_list)

    @property
    def doc_path(self) -> Path:
        domain_list, base_name, extension = self._decompose_id()

        doc_path = self.base_path
        for domain in domain_list:
            doc_path = doc_path / domain
        doc_path = (doc_path / base_name).with_suffix(f".{extension}")

        return doc_path

    def _decompose_id(self) -> tuple[list[str], str, str]:
        splitted = self.id.split(".")
        if self.extension:
            domain_list = splitted[:-1]
            base_name = splitted[-1]
            extension = self.extension
        else:
            ext_candidate = splitted[-1]
            extensions = self.registry_doc_type.extensions
            _found = next((ext for ext in extensions if ext == ext_candidate), None)
            if _found:
                domain_list = splitted[:-2]
                base_name = splitted[-2]
                extension = splitted[-1]
            else:
                domain_list = splitted[:-1]
                base_name = splitted[-1]
                extension = extensions[0]

        return domain_list, base_name, extension

    def load(self) -> Any:
        doc_path = self.doc_path
        if not doc_path.exists():
            raise DocumentReadingError(
                f"Document '{self.id}' not found at '{doc_path}'"
            )

        handler = self.registry_doc_handler
        if handler.deserializer is None:
            raise DocumentReadingError(
                f"No deserializer registered for doc_type='{self.doc_type}', doc_model='{self.doc_model}'"
            )
        return handler.deserializer(doc_path)

    def save(self, data: Any) -> Path:
        expected_type = self.registry_doc_model.clazz
        if not isinstance(data, expected_type):
            raise TypeError(
                f"Expected instance of {expected_type.__name__} for doc_model "
                f"'{self.doc_model}', got {type(data).__name__}"
            )

        handler = self.registry_doc_handler
        if handler.serializer is None:
            raise DocumentWritingError(
                f"No serializer registered for doc_type='{self.doc_type}', doc_model='{self.doc_model}'"
            )

        doc_path = self.doc_path
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        handler.serializer(data, doc_path)
        return doc_path

    def copy_to(self, target: DocumentReference) -> DocumentReference:
        if self.doc_model != target.doc_model:
            raise DocumentWritingError(
                f"Cannot copy a '{self.doc_model}' to '{target.doc_model}'"
            )

        src_path = self.doc_path
        if not src_path.exists():
            raise DocumentWritingError(
                f"Document '{self.id}' not found at '{src_path}'"
            )

        dst_path = target.doc_path

        if dst_path != src_path:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if self.doc_type == target.doc_type:
                shutil.copy2(src_path, dst_path)
            else:
                target.save(self.load())

        return target


class DocumentContext(BaseDatorumPersistentSettings):
    """Collection of managed document references and domain metadata."""

    id: str = Field(description="Context scope identifier.")
    documents: dict[str, DocumentReference] = Field(default_factory=dict)
    domain_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)

    _base_path: Path | None = PrivateAttr(default=None)

    @property
    def base_path(self) -> Path:
        if self._base_path is None:
            return self.settings_path.parent
        return self._base_path

    @base_path.setter
    def base_path(self, value: Path):
        self._base_path = value

    def knows_domain(self, domain: str) -> bool:
        if domain in self.domain_metadata:
            return True

        return any(doc.startswith(f"{domain}.") for doc in self.documents)

    def get_domain_path(self, domain: str) -> Path:
        domain_path = self.base_path
        for step in domain.split("."):
            domain_path /= step
        return domain_path

    def get_domain_metadata(self, domain: str) -> dict[str, Any] | None:
        if domain not in self.domain_metadata:
            return None
        return self.domain_metadata[domain]

    def set_domain_metadata(self, domain: str, metadata: dict[str, Any]):
        self.domain_metadata[domain] = metadata.copy()

    def get_document(self, id: str) -> DocumentReference | None:
        return self.documents.get(id)

    def create_document(
        self,
        id: str,
        doc_type: str = "text/plain",
        doc_model: str = "text",
        extension: str | None = None,
    ) -> DocumentReference:
        document = DocumentReference(
            id=id,
            doc_type=doc_type,
            doc_model=doc_model,
            extension=extension,
        )
        self.documents[id] = document
        document._set_persistent_recursive(self)
        return document

    def drop_document(self, id: str, remove_file: bool = False):
        if remove_file:
            doc_path = self.documents[id].doc_path
            if doc_path.exists():
                doc_path.unlink()
        del self.documents[id]

    def _set_persistent_recursive(self, persistent_instance, visited=None):
        super()._set_persistent_recursive(persistent_instance, visited)
        for doc in self.documents.values():
            doc._persistent = self
