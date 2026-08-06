from pathlib import Path

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from .exceptions import InvalidIdentifierException
from .settings import BaseDatorumSettings
from .context import doc_model, serializer, deserializer, simple_json_writer, simple_json_reader


class AIServiceProvider(BaseDatorumSettings):
    """OpenAI-compatible API service provider settings."""

    id: str
    base_url: str = Field(description="API endpoint base URL (usually ending in 'v1/')")
    supports_streaming: bool = True

    description: str | None = Field(default=None)
    api_key_hint: str | None = Field(default=None)

    default_model: str | None = Field(default=None)
    models: list[str] = Field(default_factory=list)

    _resolved_key: str | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _default_model_must_be_listed(self) -> "AIServiceProvider":
        if (
            self.default_model is not None
            and self.models
            and self.default_model not in self.models
        ):
            raise InvalidIdentifierException(
                f"default_model '{self.default_model}' not in provider '{self.id}' models list"
            )
        return self


class AgentRole(BaseDatorumSettings):
    """Role based API call parameters."""

    id: str
    description: str | None = None
    preferred_models: list[str] = Field(default_factory=list)
    system_instructions: str = Field(default="")
    user_prompt: str = Field(default="")
    temperature: float = Field(default=0.5)
    top_p: float = Field(default=1.0)
    max_tokens: int = Field(default=4096)


class AIConfig(BaseDatorumSettings):
    """Daturum configuration data structure."""

    providers: list[AIServiceProvider] = Field(default_factory=list)
    roles: list[AgentRole] = Field(default_factory=list)

    def get_provider(self, provider_id: str) -> AIServiceProvider:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise InvalidIdentifierException(f"No provider with id '{provider_id}'")

    def get_role(self, role_id: str) -> AgentRole:
        for role in self.roles:
            if role.id == role_id:
                return role
        raise InvalidIdentifierException(f"No role with id '{role_id}'")

    def _validate_unique(self, field: str, ids: list[str]) -> None:
        if len(ids) != len(set(ids)):
            from collections import Counter

            duplicates = [id for id, count in Counter(ids).items() if count > 1]
            raise InvalidIdentifierException(
                f"Duplicate child IDs found in 'AIConfig.{field}': {duplicates}"
            )

    @model_validator(mode="after")
    def _bind_providers_to_self(self) -> "AIConfig":

        self._validate_unique("providers", [p.id for p in self.providers])
        self._validate_unique("roles", [r.id for r in self.roles])

        return self

from typing import Optional, Union, List, Annotated, Literal
from pydantic import BaseModel, Field, model_validator


# ************************************************************
# * * * * * * * * * * * *  Chat Model  * * * * * * * * * * * *
# ************************************************************


# ============================
# 1. Content blocks for vision / multimodal
# ============================
class ImageUrl(BaseModel):
    url: str
    detail: Optional[Literal["low", "high", "auto"]] = "auto"


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageUrl


# User content can be plain text or a mixed list of text and images.
ContentPart = Annotated[Union[TextPart, ImagePart], Field(discriminator="type")]
UserContent = Union[str, List[ContentPart]]


# ============================
# 2. Function calls / Tools
# ============================
class FunctionCall(BaseModel):
    """Old (deprecated) function call format."""
    name: str
    arguments: str  # String JSON


class ToolFunction(BaseModel):
    """Function definition within a tool_call."""
    name: str
    arguments: str  # String JSON


class ToolCall(BaseModel):
    """Tool call in the new format (tools)."""
    id: str
    type: Literal["function"] = "function"
    function: ToolFunction


# ============================
# 3. Message definitions (Discriminated Union based on the 'role' field)
# ============================
class _MessageBase(BaseModel):
    """Base class to validate that extra fields are not allowed."""
    name: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    model_config = {"extra": "forbid"}

    def prepare_request(self) -> dict[str, Any]:
        known_fields = set(type(self).model_fields.keys()) - {"metadata"}
        return self.model_dump(mode="json", exclude_none=True, include=known_fields)


class SystemMessage(_MessageBase):
    role: Literal["system"] = "system"
    content: str


class UserMessage(_MessageBase):
    role: Literal["user"] = "user"
    content: UserContent


class AssistantMessage(_MessageBase):
    role: Literal["assistant"] = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    function_call: Optional[FunctionCall] = None  # Deprecated, but retained for compatibility

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def validate_assistant(self):
        """TODO validation: if `tool_calls` is present, `content` is `None` or empty."""
        return self


class ToolMessage(_MessageBase):
    """Response from a called tool."""
    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str  # Required for 'tool' messages


class FunctionMessage(_MessageBase):
    """Response from a called function (old format)."""
    role: Literal["function"] = "function"
    content: Optional[str] = None
    name: str  # Mandatory and overrides the optional base field.


# Combination of all message types, distinguished by the 'role' field.
ChatMessage = Annotated[
    Union[
        SystemMessage,
        UserMessage,
        AssistantMessage,
        ToolMessage,
        FunctionMessage,
    ],
    Field(discriminator="role"),
]


# ============================
# 4. Main History Model
# ============================
@doc_model(id="chat-history")
class ChatHistory(BaseModel):
    """Represents the complete message history for the OpenAI API."""
    messages: List[ChatMessage] = Field(
        ...,
        default_factory=list,
        description="Ordered list of chat history messages"
    )

    model_config = {"extra": "forbid"}
