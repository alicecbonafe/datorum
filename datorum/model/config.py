import base64
from collections.abc import Callable
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from enum import Enum
import getpass
import json
import os
from pathlib import Path
from typing import Literal, Optional, Annotated, Union

import keyring
from pydantic import Field, PrivateAttr, model_validator

from .base import BaseDatorumModel, BaseDatorumPersistentModel
from ..exceptions import InvalidIdentifierException, KeyStoreException


class KeyStore(BaseDatorumModel):
    """Interface class for safe key stores."""

    type: str
    _unlocked: bool = PrivateAttr(default=False)

    def unlock(self, password_provider: Callable[[str], str] | None = None) -> None:
        self._unlocked = True

    def load_key(self, provider_id: str) -> str:
        raise NotImplementedError

    def store_key(self, provider_id: str, api_key: str) -> str:
        raise NotImplementedError

    def _ensure_unlocked(self) -> None:
        if not self._unlocked:
            raise KeyStoreException("Key store is locked")


class NoKeyStore(KeyStore):
    """Dummy key store for config initializing."""

    type: Literal["none"] = "none"

    def unlock(self, password_provider: Callable[[str], str] | None = None) -> None:
        raise KeyStoreException("No key store configured; set one with 'datorum keys set'")

    def load_key(self, provider_id: str) -> str:
        raise KeyStoreException("No key store configured; set one with 'datorum keys set'")

    def store_key(self, provider_id: str, api_key: str) -> str:
        raise KeyStoreException("No key store configured; set one with 'datorum keys set'")


class OSKeychainStore(KeyStore):
    """OS-provided keychain store."""

    type: Literal["os_keychain"] = "os_keychain"
    service: str = Field("datorum", description="Keychain namespace, override for multiple profiles")

    def load_key(self, provider_id: str) -> str:
        key = keyring.get_password(self.service, provider_id)
        if key is None:
            raise KeyStoreException(f"No key found in OS keychain for '{provider_id}'")
        return key

    def store_key(self, provider_id: str, api_key: str) -> str:
        keyring.set_password(self.service, provider_id, api_key)
        return api_key


class EncryptedFileStore(KeyStore):
    """Encrypted local file key store."""

    type: Literal["encrypted_file"] = "encrypted_file"
    encrypted_file: str = Field(description="Name to the encrypted file.")
    iterations: int = Field(600_000, ge=100_000, description="Key derivation iterations.")

    _fernet: Fernet | None = PrivateAttr(default=None)

    @property
    def encrypted_path(self) -> Path:
        return self.settings_path / self.encrypted_file

    def load_key(self, provider_id: str) -> str:
        key = self._load().get(provider_id)
        if key is None:
            raise KeyStoreException(f"No key found for '{provider_id}' in encrypted file store")
        return key

    def store_key(self, provider_id: str, api_key: str) -> str:
        data = self._load()
        data[provider_id] = api_key
        self._save(data)
        return api_key

    def unlock(
        self,
        password_provider: Callable[[str], str] = getpass.getpass,
    ) -> None:
        if self._unlocked:
            return

        try:
            password = password_provider(f"Password for {self.encrypted_file}: ")
        except Exception as exc:
            raise KeyStoreException(f"Could not obtain key store password: {exc}") from exc

        if not password:
            raise KeyStoreException("Key store password cannot be empty")

        salt = self._read_or_create_salt()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32,
            salt=salt, iterations=self.iterations,
        )
        derived = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
        self._fernet = Fernet(derived)
        self._unlocked = True

    def _read_or_create_salt(self) -> bytes:
        if not self.encrypted_path.exists():
            self.encrypted_path.parent.mkdir(parents=True, exist_ok=True)
            salt = os.urandom(16)
            self.encrypted_path.write_text(json.dumps({
                "salt": base64.b64encode(salt).decode(), "data": None,
            }))
            return salt
        payload = json.loads(self.encrypted_path.read_text(encoding="utf-8"))
        return base64.b64decode(payload["salt"])

    def _load(self) -> dict[str, str]:
        self._ensure_unlocked()
        payload = json.loads(self.encrypted_path.read_text(encoding="utf-8"))
        if not payload.get("data"):
            return {}
        try:
            raw = self._fernet.decrypt(payload["data"].encode("utf-8"))
        except InvalidToken:
            raise KeyStoreException("Wrong password, or the key store file is corrupted")
        return json.loads(raw)

    def _save(self, data: dict[str, str]) -> None:
        self._ensure_unlocked()
        salt = self._read_or_create_salt()
        encrypted = self._fernet.encrypt(json.dumps(data).encode("utf-8"))
        self.encrypted_path.write_text(json.dumps({
            "salt": base64.b64encode(salt).decode(),
            "data": encrypted.decode("utf-8"),
        }))


class AIServiceProvider(BaseDatorumModel):
    """OpenAI-compatible API service provider settings."""

    id: str
    base_url: str = Field(description="API endpoint base URL (usually ending in 'v1/')")

    description: str | None = Field(default=None)
    api_key_hint: str | None = Field(default=None)

    default_model: str | None = Field(default=None)
    models: list[str] = Field(default_factory=list)

    _resolved_key: str | None = PrivateAttr(default=None)

    @property
    def config(self) -> 'GeneralConfig':
        if isinstance(self.persistent, GeneralConfig):
            return self.persistent
        raise ValueError("Config not found")

    @property
    def api_key(self) -> str:
        if self._resolved_key is None:
            self._resolved_key = self.config.key_store.load_key(self.id)
        return self._resolved_key

    @api_key.setter
    def api_key(self, api_key: str):
        self.config.key_store.store_key(self.id, api_key)
        self._resolved_key = api_key
        self.api_key_hint = f"{api_key[:7]}..."

    @model_validator(mode="after")
    def _default_model_must_be_listed(self) -> "GeneralConfig":
        if self.default_model is not None and self.models and self.default_model not in self.models:
            raise InvalidIdentifierException(
                f"default_model '{self.default_model}' not in provider '{self.id}' models list"
            )
        return self


class AgentRole(BaseDatorumModel):
    """Role based API call parameters."""

    id: str
    description: str | None = None
    preferred_models: list[str] = Field(default_factory=list)
    system_instructions: str = Field(default="")
    user_prompt: str = Field(default="")
    temperature: float = Field(default=0.5)
    top_p: float = Field(default=1.0)
    max_tokens: int = Field(default=4096)


class GeneralConfig(BaseDatorumPersistentModel):
    """Daturum configuration data structure."""

    log_file: str | None = Field(default=None, description="Name for the log file.")
    key_store: OSKeychainStore | EncryptedFileStore | NoKeyStore = Field(default_factory=NoKeyStore, discriminator="type")

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
                f"Duplicate child IDs found in 'GeneralConfig.{field}': {duplicates}"
            )

    @model_validator(mode="after")
    def _bind_providers_to_self(self) -> "GeneralConfig":

        self._validate_unique("providers", [p.id for p in self.providers])
        self._validate_unique("roles", [r.id for r in self.roles])

        return self

