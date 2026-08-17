from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .context.registry import (
    validate_factory_signature,
    get_resource_factory,
)
from .context.settings import (
    DocumentContext,
    ContextBind,
    ResourceBind,
)
from .context.binder import Binder
from .core.security import SecurityBackend
from .work.job import Broadcaster, Job
from .work.worker import Worker
from .tooling.settings import ToolKit, ToolBoxSetUp
from .tooling.worker import ToolWorker
from .agency.settings import AgencyKit
from .agency.worker import AgentWorker
from .plumbing.settings import PlumbingKit, PipeFlow
from .plumbing.worker import PipelineWorker




class DatorumProfile:

    def __init__(self,
        username: str,
        toolkit_path: Path,
        agencykit_path: Path,
        plumbingkit_path: Path,
        flow_settings_path: Path,
    ):
        self.toolkit: ToolKit = ToolKit.load(toolkit_path)
        self.agencykit: AgencyKit = AgencyKit.load(agencykit_path)
        self.plumbingkit: PlumbingKit = PlumbingKit.load(plumbingkit_path)

        username: str
        flows: dict[str, PipeFlow] = field(default_factory=dict)
        jobs: dict[str, Job] = field(default_factory=dict)

        self.tool_worker: ToolWorker = ToolWorker(
            toolkit=self.toolkit
        )
        self.agent_worker: AgentWorker = AgentWorker(
            agency_kit=self.agencykit,
            tool_worker=self.tool_worker
        )
        self.pipeline_worker: PipelineWorker = PipelineWorker(
            flow_settings_path=flow_settings_path,
            agent_worker=self.agent_worker,
            tool_worker=self.tool_worker,
        )





    ai_config: Optional[AgencyKit] = field(default=None)
    pipeline_collection: Optional[PipelineCollection] = field(default=None)
    toolkit: Optional[ToolKit] = field(default=None)
    contexts: dict[str, DocumentContext] = field(default_factory=dict)
    factories: dict[str, Callable] = field(default_factory=dict)


    def load_ai_config(self, settings_path: Path):
        self.ai_config = AgencyKit.load(
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



