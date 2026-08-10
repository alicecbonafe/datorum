from pathlib import Path
from typing import Optional


from ..context import DocumentContext
from ..inference import AIConfig
from ..pipeline import PipelineCollection
from ..security import SecurityBackend
from ..tooling import ToolBoxSetUp
from .base import Worker


class DatorumProfile():
    username: str
    ai_config: Optional[AIConfig] = None
    context_collection: dict[str, DocumentContext]

    workers: dict[str, Worker] = {}


class DatorumOrquestrator():

    def __init__(self,
        security_backend: SecurityBackend,
        pipelines: PipelineCollection | Path,
        ai_config: Optional[AIConfig | Path] = None,
    ):
        self.security_backend = security_backend
        self.pipelines: PipelineCollection = pipelines \
            if isinstance(pipelines, PipelineCollection) \
                else PipelineCollection.load(pipelines)
        self.ai_config: Optional[AIConfig] = ai_config \
            if ai_config is None or isinstance(ai_config, AIConfig) \
                else AIConfig.load(ai_config)

        self.context_collection: dict[str, DocumentContext] = {}
        self.toolbox_collection: dict[str, ToolBoxSetUp] = {}

        self.profiles: dict[str, DatorumProfile] = {}
        self.sessions: dict[str, str] = {}

    def create_profile(self,
        username: str,
        ai_config: Optional[AIConfig | Path] = None,
        context_collection: dict[str, DocumentContext] | None = None) -> DatorumProfile:...

    def get_profile(self, *, username: str | None = None, token: str | None = None) -> Optional[DatorumProfile]:...

    def register_session(self, username: str, token: str):
        if token not in self.sessions.items():
            for key, val in self.sessions:
                if val == username:
                    del self.sessions[key]
            self.sessions[token] = username

    def drop_session(self, token: str):
        if token in self.sessions:
            del self.sessions[token]

    def load_context(self, token: str, context_file_path: Path) -> str:...

    def load_global_context(self, context_file_path: Path) -> str:...

    def load_toolbox(self, toolbox_file_path: Path) -> str:...

    def prepare_tool_worker(self,
        token: str,
        toolbox_setup_id: str,
        tool_name: str,
    ) -> str:...

    def prepare_agent_worker(self,
        token: str,
        provider_id: str,
        role_id: str,
    ) -> str:...

    def prepare_pipeline_worker(self,
        token: str,
        pipeline_id: str,
    ) -> str:...

    def prepare_job(self,
        token: str,
        worker_id: str,
        documents: list[tuple[str | None, str]],
    ) -> str:...

    def prepare_worflow(self,
        token: str,
        worker_id: str,
        contexts: list[str],
    ) -> str:...

    def start_job(self,
        token: str,
        job_id: str,
    ):...

    def request_job_pause(self,
        token: str,
        job_id: str,
    ):...

    def get_job_status(self,
        token: str,
        job_id: str,
    ) -> dict:...

    async def stream_chunks(self,
        token: str,
        job_id: str,
    ) -> AsyncGenerator[str, None]:...

    async def stream_logs(self,
        token: str,
        job_id: str,
    ) -> AsyncGenerator[str, None]:...


