from typing import Literal

from pydantic import Field

from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class InferenceServiceProvider(BaseDatorumSettings):
    """OpenAI-compatible API service provider settings."""
    id: str
    description: str | None = Field(default=None)

    base_url: str = Field(description="API endpoint base URL (usually ending in 'v1/').")
    api_key_selector: str | None = Field(default=None, description="Used if API key resource selector is not the provider ID.")
    supports_streaming: bool = True

    models: list[str] = Field(default_factory=list)


class AgentRole(BaseDatorumSettings):
    """Role based API call parameters."""
    id: str
    description: str | None = Field(default=None)

    preferred_models: list[str] = Field(default_factory=list)
    system_instructions: str | None = Field(default=None)

    temperature: float = Field(default=0.5)
    top_p: float = Field(default=1.0)
    max_tokens: int = Field(default=4096)
    output_doc_model: str | None = Field(default=None)

    tools_enabled: list[str] = Field(default_factory=list)
    tool_choice: Literal["auto", "none", "required"] = Field(default="auto")
    tool_max_iter: int = Field(default=3)


class AgencyKit(BaseDatorumPersistentSettings):
    """Daturum configuration data structure."""
    providers: dict[str, InferenceServiceProvider] = Field(default_factory=dict)
    roles: dict[str, AgentRole] = Field(default_factory=dict)
