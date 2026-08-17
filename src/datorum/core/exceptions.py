class DatorumBaseError(Exception):
    """Base class for all Datorum errors."""
    ...


class SettingsError(DatorumBaseError):
    """Settings related errors."""
    ...


class RegistryError(DatorumBaseError):
    """Registry related errors."""
    ...

