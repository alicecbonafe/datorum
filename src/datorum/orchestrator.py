from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..binding import (
    ContentType,
    Binder, ContextBind, ResourceBind,
    validate_factory_signature, get_resource_factory
)
from ..context import DocumentContext
from ..exceptions import OrchestratorException, InvalidContextBindException
from ..inference import AIConfig
from ..pipeline import PipelineCollection, PipeFlow
from ..security import SecurityBackend
from ..tooling import ToolBoxSetUp, ToolKit
from .base import Broadcaster, Worker, Job


@dataclass
class DatorumProfile(Binder):
    ai_config: Optional[AIConfig] = field(default=None)
    pipeline_collection: Optional[PipelineCollection] = field(default=None)
    toolkit: Optional[ToolKit] = field(default=None)
    contexts: dict[str, DocumentContext] = field(default_factory=dict)
    factories: dict[str, Callable] = field(default_factory=dict)


    def load_ai_config(self, settings_path: Path):
        self.ai_config = AIConfig.load(
            settings_path=settings_path)

    def load_pipeline_collection(self, settings_path: Path):
        self.pipeline_collection = PipelineCollection.load(
            settings_path=settings_path)

    def load_toolkit(self, settings_path: Path):
        self.toolkit = ToolKit.load(
            settings_path=settings_path)

    def load_context(self, settings_path: Path, base_path: Optional[Path] = None) -> DocumentContext:
        context = DocumentContext.load(
            settings_path=settings_path)
        if base_path is not None:
            context.base_path = base_path
        self.contexts[context.id] = context
        return context


@dataclass
class DatorumUserProfile(DatorumProfile):
    username: str
    flows: dict[str, PipeFlow] = field(default_factory=dict)
    jobs: dict[str, Job] = field(default_factory=dict)

    def load_flow(self, settings_path: Path): ...

class DatorumOrquestrator:

    def __init__(self,
        security_backend: SecurityBackend,
        global_profile: DatorumProfile,
    ):
        self.security_backend = security_backend
        self.global_profile: DatorumProfile = global_profile

        self.user_profiles: dict[str, DatorumProfile] = {}
        self.sessions: dict[str, str] = {}

    def register_user_profile(self, profile: DatorumUserProfile, force: bool = False) -> DatorumProfile:
        if profile.username in self.user_profiles and not force:
            raise OrchestratorException(f"Profile already registered for username '{profile.username}', use 'force=True' to overwrite")
        self.user_profiles[profile.username] = profile
        return profile

    def get_profile(self, *, username: str | None = None, token: str | None = None) -> Optional[DatorumProfile]:
        if username is None and token is None:
            raise OrchestratorException("No profile identifier, one of 'token' and 'username' params must be specified")

        if token is not None and token not in self.sessions:
            raise OrchestratorException("Invalid session token")

        return self.user_profiles[
            username or self.sessions[token]
        ]

    def register_session(self, username: str, token: str):
        if token not in self.sessions.items():
            for key, val in self.sessions:
                if val == username:
                    del self.sessions[key]
            self.sessions[token] = username

    def drop_session(self, token: str):
        if token in self.sessions:
            del self.sessions[token]



