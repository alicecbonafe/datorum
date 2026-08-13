from enum import Enum
from pathlib import Path
import shutil
from typing import Any, Optional

from pydantic import Field, PrivateAttr

from ..exceptions import (
    DocumentFormatException,
    DocumentNotFoundException,
    UnknownDataModelException,
    InvalidIdentifierException,
)
from ..registry.documents import (
    get_doc_type,
    get_doc_model,
    find_handlers,
)
from .base import BaseDatorumSettings, BaseDatorumPersistentSettings


class DocumentReference(BaseDatorumSettings):
    id: str
    doc_type: str = "text/plain"
    doc_model: str = "text"

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def registry_doc_type(self) -> DocumentType:
        try:
            return get_doc_type(self.doc_type)
        except InvalidIdentifierException:
            raise DocumentFormatException(
                f"Unknown doc_type '{self.doc_type}'"
            ) from None

    @property
    def registry_doc_model(self) -> DocumentModel:
        try:
            return get_doc_model(self.doc_model)
        except InvalidIdentifierException:
            raise UnknownDataModelException(
                f"Unknown doc_model '{self.doc_model}'"
            ) from None

    @property
    def registry_doc_handler(self) -> DocumentHandler:
        handlers = find_handlers(doc_type=self.doc_type, doc_model=self.doc_model)
        if not handlers:
            raise DocumentFormatException(
                f"No handler registered for doc_type='{self.doc_type}', doc_model='{self.doc_model}'"
            )
        return handlers[0]

    @property
    def base_path(self) -> Path:
        if hasattr(self.persistent, "base_path") and self.persistent.base_path:
            return self.persistent.base_path
        return self.settings_path.parent

    @property
    def name(self) -> str:
        return self.id.split(".")[-1]

    @property
    def domain_list(self) -> list[str]:
        return self.id.split(".")[:-1]

    @property
    def domain(self) -> str:
        return ".".join(self.domain_list)

    @property
    def doc_path(self) -> Path:
        name = self.name
        domain_list = self.domain_list

        doc_path = self.base_path
        for domain in domain_list:
            doc_path = doc_path / domain
        doc_path = doc_path / name

        extentions = self.registry_doc_type.extentions
        has_ext = any(name.endswith(f".{ext}") for ext in extentions)
        if not has_ext and extentions:
            doc_path = doc_path.with_suffix(f".{extentions[0]}")

        return doc_path

    def load(self) -> Any:
        doc_path = self.doc_path
        if not doc_path.exists():
            raise DocumentNotFoundException(
                f"Document '{self.id}' not found at '{doc_path}'"
            )

        handler = self.registry_doc_handler
        if handler.deserializer is None:
            raise DocumentFormatException(
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
            raise DocumentFormatException(
                f"No serializer registered for doc_type='{self.doc_type}', doc_model='{self.doc_model}'"
            )

        doc_path = self.doc_path
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        handler.serializer(data, doc_path)
        return doc_path

    def copy_to(self, target: "DocumentReference") -> "DocumentReference":
        if self.doc_model != target.doc_model:
            raise DocumentFormatException(
                f"Cannot copy a '{self.doc_model}' to '{target.doc_model}'"
            )

        src_path = self.doc_path
        if not src_path.exists():
            raise DocumentNotFoundException(
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
    id: str
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

        return any(
            doc.startswith(f"{domain}.")
            for doc in self.documents.keys()
        )

    def get_domain_path(self, domain: str) -> Path:
        domain_path = self.base_path
        for step in domain.split("."):
            domain_path /= step
        return domain_path

    def get_domain_metadata(self, domain: str) -> Optional[dict[str, Any]]:
        if domain not in self.domain_metadata:
            return None
        return self.domain_metadata[domain]

    def set_domain_metadata(self, domain: str, metadata: dict[str, Any]):
        self.domain_metadata[domain] = metadata.copy()

    def get_document(self, id: str) -> DocumentReference | None:
        return self.documents.get(id)

    def create_document(
        self, id: str, doc_type: str = "text/plain", doc_model: str = "text"
    ) -> DocumentReference:
        document = DocumentReference(
            id=id,
            doc_type=doc_type,
            doc_model=doc_model,
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


class ContextBindType(str, Enum):
    model = "model"
    model_input = "model-input"
    model_output = "model-output"
    text = "text"
    text_input = "text-input"
    text_output = "text-output"
    bytes = "bytes"
    bytes_input = "bytes-input"
    bytes_output = "bytes-output"
    document_path = "document-path"
    document_metadata = "document-metadata"
    domain_path = "domain-path"
    domain_metadata = "domain-metadata"

    def is_domain(self) -> bool:
        return self.value.startswith("domain")

    def is_input(self) -> bool:
        return not self.value.endswith("output")

    def is_output(self) -> bool:
        return not self.value.endswith("input") \
            and not self.value.endswith("path")

    def is_model(self) -> bool:
        return self.value.startswith("model")

    def is_text(self) -> bool:
        return self.value.startswith("text")

    def is_bytes(self) -> bool:
        return self.value.startswith("bytes")

    def is_path(self) -> bool:
        return self.value.endswith("path")

    def is_metadata(self) -> bool:
        return self.value.endswith("metadata")

    def is_io(self) -> bool:
        return self.is_model() or self.is_text() or self.is_bytes()


class ContextBind(BaseDatorumSettings):
    binded_id: str
    context: str | list[str] | None = Field(default=None)
    context_bind_type: ContextBindType = Field(default=ContextBindType.model)


class ResourceBind(BaseDatorumSettings):
    factory_name: str
    selector: str | None = None
