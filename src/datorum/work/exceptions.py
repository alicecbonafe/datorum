from ..core.exceptions import DatorumBaseError


class JobError(DatorumBaseError):
    """Base exception class for job failure."""


class JobStatusError(JobError):
    """Raised on invalid job lifecycle state transition."""


class WorkerError(DatorumBaseError):
    """Base exception class for worker errors."""


class WorkerStartUpError(WorkerError):
    """Raised when worker initialization requirements are unmet."""
