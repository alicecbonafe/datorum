from ..core.exceptions import RegistryError, SettingsError


class DocumentTypeError(RegistryError):
    """Raised for errors in document type resolution or registration."""


class DocumentModelError(RegistryError):
    """Raised for errors in document model resolution or registration."""


class DocumentHandlerError(RegistryError):
    """Raised when no serializer or deserializer handler is available."""


class DocumentReferenceError(SettingsError):
    """Base error for document file referencing issues."""


class DocumentReadingError(DocumentReferenceError):
    """Raised when reading or deserializing a document fails."""


class DocumentWritingError(DocumentReferenceError):
    """Raised when writing or serializing a document fails."""
