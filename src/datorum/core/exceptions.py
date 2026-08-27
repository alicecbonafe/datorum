class DatorumBaseError(Exception):
    """Base exception class for all errors in the Datorum framework."""


class SettingsError(DatorumBaseError):
    """Raised when an error occurs during settings initialization or persistence."""


class RegistryError(DatorumBaseError):
    """Raised when registry lookup or registration operations fail."""
