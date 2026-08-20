from ..core.exceptions import RegistryError
from ..work.exceptions import WorkerError


class ToolBoxRegistryError(RegistryError): ...


class ToolWorkerError(WorkerError): ...
