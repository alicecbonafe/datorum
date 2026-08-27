from ..work.exceptions import WorkerError


class AgentWorkerError(WorkerError):
    """Raised when agent execution or inference provider communication fails."""
