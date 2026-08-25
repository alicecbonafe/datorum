from ..core.exceptions import RegistryError
from ..work.exceptions import WorkerError


class ToolBoxRegistryError(RegistryError):
    """Raised for errors during toolbox registration or definition lookup."""


class ToolWorkerError(WorkerError):
    """Raised when tool execution fails."""
