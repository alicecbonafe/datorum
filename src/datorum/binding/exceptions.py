from ..core.exceptions import DatorumBaseError, RegistryError


class ResourceFactoryError(RegistryError):
    """Raised for errors in resource factory lookup or registration."""


class BinderError(DatorumBaseError):
    """Base error for binder resolution operations."""


class ResourceBindingError(BinderError):
    """Raised when resolving a resource binding fails."""


class ContextBindingError(BinderError):
    """Raised when context binding resolution or transfer fails."""


class CredentialError(DatorumBaseError):
    """Base class for credential and key lookup errors."""


class KeyNotFoundError(CredentialError):
    """Raised when the factory cannot resolve a requested API key."""


class InvalidKeyNameError(CredentialError):
    """Raised when an API key identifier fails format validation."""
