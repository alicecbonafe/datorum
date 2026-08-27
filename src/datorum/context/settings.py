import shutil
from pathlib import Path
from typing import Any

from pydantic import Field, PrivateAttr

from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings
from .exceptions import (
    DocumentReadingError,
    DocumentReferenceError,
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
    """Reference pointing to a physical document on disk within a context.

    The `id` doubles as the document's dotted path within the context: leading
    segments become domain folders and the last segment becomes the file's base name.
    The file's on-disk extension is resolved from `extension` when set, or otherwise
    inferred from the registered `DocumentType` for `doc_type`.
    """

    id: str = Field(description="Unique document identifier within the context.")
    doc_type: str = Field(
        default="text/plain",
        description="MIME content type, defaults to 'text/plain'.",
    )
    doc_model: str = Field(
        default="text",
        description="Document model type, defaults to 'text'.",
    )
    extension: str | None = Field(
        default=None,
        description="Explicit file extension override."
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary user-defined metadata associated with the document.",
    )

    @property
    def context(self) -> DocumentContext:
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
        """Read and deserialize the document from disk.

        :returns: Deserialized document data, typed per the registered doc model.
        :rtype: Any
        :raises DocumentReadingError: If the file is missing or no deserializer is
            registered for the document's `doc_type`/`doc_model` pair.
        """

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
        """Serialize and write `data` to disk at this reference's document path.

        :param data: Instance of the document's registered model class to persist.
        :type data: Any
        :returns: Path the document was written to.
        :rtype: pathlib.Path
        :raises DocumentReferenceError: If `data` isn't an instance of the registered doc model class.
        :raises DocumentWritingError: If no serializer is registered for the document's
            `doc_type`/`doc_model` pair.
        """

        expected_type = self.registry_doc_model.clazz
        if not isinstance(data, expected_type):
            raise DocumentReferenceError(
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
        """Copy this document's content to another reference's location.

        When both references share the same `doc_type`, the underlying file is copied
        directly; otherwise the source is loaded and re-serialized through `target`.

        :param target: Destination document reference. Must share this reference's `doc_model`.
        :type target: DocumentReference
        :returns: The `target` reference, for chaining.
        :rtype: DocumentReference
        :raises DocumentWritingError: If `doc_model` differs between the two references,
            or the source file doesn't exist.
        """

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
    """Collection of managed document references and domain metadata.

    A context is the persistent, shared knowledge base a `Binder` resolves context
    bindings against; `Binder` also creates smaller, per-job local contexts by copying
    documents out of a shared context on demand.
    """

    id: str = Field(description="Context scope identifier.")
    documents: dict[str, DocumentReference] = Field(
        default_factory=dict,
        description="Document references managed within this context, keyed by ID.",
    )
    domain_metadata: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Arbitrary metadata keyed by domain name.",
    )

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
        """Check whether a domain has metadata or at least one document in it.

        :param domain: Dotted domain name.
        :type domain: str
        :returns: True if the domain has metadata registered or any document whose ID
            is prefixed with it.
        :rtype: bool
        """

        if domain in self.domain_metadata:
            return True

        return any(doc.startswith(f"{domain}.") for doc in self.documents)

    def get_domain_path(self, domain: str) -> Path:
        """Resolve the on-disk folder path corresponding to a domain.

        :param domain: Dotted domain name.
        :type domain: str
        :returns: Path to the domain's folder under `base_path`.
        :rtype: pathlib.Path
        """

        domain_path = self.base_path
        for step in domain.split("."):
            domain_path /= step
        return domain_path

    def get_domain_metadata(self, domain: str) -> dict[str, Any] | None:
        """Retrieve the metadata dict registered for a domain, if any.

        :param domain: Dotted domain name.
        :type domain: str
        :returns: Metadata dict, or None if the domain has no metadata registered.
        :rtype: dict[str, Any] | None
        """

        if domain not in self.domain_metadata:
            return None
        return self.domain_metadata[domain]

    def set_domain_metadata(self, domain: str, metadata: dict[str, Any]):
        """Set (replacing) the metadata dict for a domain.

        :param domain: Dotted domain name.
        :type domain: str
        :param metadata: Metadata to store; a shallow copy is kept.
        :type metadata: dict[str, Any]
        """

        self.domain_metadata[domain] = metadata.copy()

    def get_document(self, id: str) -> DocumentReference | None:
        """Retrieve a managed document reference by ID.

        :param id: Document identifier.
        :type id: str
        :returns: The matching `DocumentReference`, or None if not found.
        :rtype: DocumentReference | None
        """

        return self.documents.get(id)

    def create_document(
        self,
        id: str,
        doc_type: str = "text/plain",
        doc_model: str = "text",
        extension: str | None = None,
    ) -> DocumentReference:
        """Create, register, and return a new document reference in this context.

        :param id: Document identifier, also used to derive its on-disk path.
        :type id: str
        :param doc_type: MIME content type, defaults to 'text/plain'.
        :type doc_type: str, optional
        :param doc_model: Document model type, defaults to 'text'.
        :type doc_model: str, optional
        :param extension: Explicit file extension override, defaults to None.
        :type extension: str | None, optional
        :returns: The newly created and registered `DocumentReference`.
        :rtype: DocumentReference
        """

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
        """Unregister a document reference from this context.

        :param id: Document identifier to remove.
        :type id: str
        :param remove_file: Whether to also delete the file on disk, defaults to False.
        :type remove_file: bool, optional
        """

        if remove_file:
            doc_path = self.documents[id].doc_path
            if doc_path.exists():
                doc_path.unlink()
        del self.documents[id]

    def _set_persistent_recursive(self, persistent_instance, visited=None):
        super()._set_persistent_recursive(persistent_instance, visited)
        for doc in self.documents.values():
            doc._persistent = self
