from ..work.exceptions import WorkerError


class PipelineWorkerError(WorkerError):
    """Raised when pipeline workflow execution fails."""
