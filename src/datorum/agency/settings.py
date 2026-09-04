from typing import Literal

from pydantic import Field

from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class InferenceServiceProvider(BaseDatorumSettings):
    """Inference API service provider settings."""

    id: str = Field(description="Provider identifier.")
    description: str | None = Field(
        default=None,
        description="Human-readable description of the provider.",
    )

    base_url: str = Field(description="Base endpoint URL.")
    timeout: float = Field(120.0, description="Timeout for this provider.")
    api_key_selector: str | None = Field(
        default=None,
        description="Used if API key resource selector is not the provider ID.",
    )
    supports_streaming: bool = Field(
        default=True,
        description="Whether this provider's completions endpoint supports streaming responses.",
    )

    models: list[str] = Field(
        default_factory=list,
        description="Model names available from this provider.",
    )


class AgentRole(BaseDatorumSettings):
    """Agent role configuration controlling inference params and default system instructions."""

    id: str = Field(description="Role identifier.")
    description: str | None = Field(
        default=None,
        description="Human-readable description of the role.",
    )

    preferred_models: list[str] = Field(
        default_factory=list,
        description="Model names, in order of preference.",
    )
    system_instructions: str | None = Field(
        default=None,
        description="Default system-instruction text for tools that construct the chat history.",
    )

    temperature: float = Field(
        default=0.5,
        description="Sampling temperature for inference requests.",
    )
    top_p: float = Field(
        default=1.0,
        description="Nucleus sampling parameter for inference requests.",
    )
    max_tokens: int = Field(
        default=4096,
        description="Maximum tokens to generate per inference request.",
    )
    output_doc_model: str | None = Field(
        default=None,
        description="Registered doc model to constrain structured output to, if any.",
    )

    tools_enabled: list[str] = Field(
        default_factory=list,
        description="Toolbox setup/tool selectors this role may call.",
    )
    tool_choice: Literal["auto", "none", "required"] = Field(
        default="auto",
        description="Tool-call policy passed to the inference API.",
    )
    tool_max_iter: int = Field(
        default=3,
        description="Maximum number of tool-call rounds per job.",
    )


class AgencyKit(BaseDatorumPersistentSettings):
    """Persistent settings managing inference providers and agent roles."""

    providers: dict[str, InferenceServiceProvider] = Field(
        default_factory=dict,
        description="Configured inference providers, keyed by provider ID.",
    )
    roles: dict[str, AgentRole] = Field(
        default_factory=dict,
        description="Configured agent roles, keyed by role ID.",
    )
