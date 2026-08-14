from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from .exceptions import InvalidIdentifierException
from .settings import BaseDatorumSettings, BaseDatorumPersistentSettings
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
    temperature: float = Field(default=0.5)
    top_p: float = Field(default=1.0)
    max_tokens: int = Field(default=4096)


class AIConfig(BaseDatorumPersistentSettings):
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
