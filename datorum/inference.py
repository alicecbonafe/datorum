from pydantic import Field, PrivateAttr, model_validator

from .exceptions import InvalidIdentifierException
from .settings import BaseDatorumSettings


class AIServiceProvider(BaseDatorumSettings):
    """OpenAI-compatible API service provider settings."""

    id: str
    base_url: str = Field(description="API endpoint base URL (usually ending in 'v1/')")

    description: str | None = Field(default=None)
    api_key_hint: str | None = Field(default=None)

    default_model: str | None = Field(default=None)
    models: list[str] = Field(default_factory=list)

    _resolved_key: str | None = PrivateAttr(default=None)

    # TODO Implement security backend calls

    # @property
    # def api_key(self) -> str:
    #     if self._resolved_key is None:
    #         self._resolved_key = self.config.key_store.load_key(self.id)
    #     return self._resolved_key

    # @api_key.setter
    # def api_key(self, api_key: str):
    #     self.config.key_store.store_key(self.id, api_key)
    #     self._resolved_key = api_key
    #     self.api_key_hint = f"{api_key[:7]}..."

    @model_validator(mode="after")
    def _default_model_must_be_listed(self) -> "AIConfig":
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
