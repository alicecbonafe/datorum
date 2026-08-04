import base64
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pydantic import BaseModel, Field, PrivateAttr

from .exceptions import ConfigException


class SecurityBackend(Protocol):
    def create_vault(self, username: str, password: str): ...

    def drop_vault(self, username: str, password: str): ...

    def change_vault_password(
        self, username: str, old_password: str, new_password: str
    ): ...

    def open_vault(self, username: str, password: str) -> str: ...

    def close_vault(self, token: str) -> str: ...

    def is_token_valid(self, token: str) -> bool: ...

    def list_key_names(self, token: str) -> list[str]: ...

    def load_key(self, token: str, key_name: str) -> str: ...

    def store_key(self, token: str, key_name: str, key_value: str) -> str: ...

    def drop_key(self, token: str, key_name: str): ...

    def get_metadata(
        self, token: str, metadata_key: str | None = None
    ) -> dict[str, str] | str: ...

    def set_metadata(self, token: str, metadata_key: str, metadata_value: str): ...


_global_security_backend: SecurityBackend | None = None


def get_security_backend() -> SecurityBackend:
    if _global_security_backend is None:
        raise ConfigException("Security backend not found")
    return _global_security_backend


def set_security_backend(backend: SecurityBackend):
    global _global_security_backend
    _global_security_backend = backend


# Fixed plaintext encrypted to build/check the password verifier, without
# ever needing to touch the real (encrypted) key data.
_VERIFIER_PLAINTEXT = b"vault-verify"


class LocalVault(BaseModel):
    username: str
    metadata: dict[str, str] = Field(default_factory=dict)

    salt: str
    iterations: int = Field(ge=100_000, description="Key derivation iterations.")
    verifier: str | None = None
    data: str | None = None


def now_factory():
    return datetime.now().astimezone()


class LocalVaultSession(BaseModel):
    token: str
    vault: LocalVault
    vault_path: Path
    idle_ttl: int = 60
    absolute_ttl: int = 1440
    created_at: datetime = Field(default_factory=now_factory)
    last_seen_at: datetime = Field(default_factory=now_factory)

    _fernet: Fernet | None = PrivateAttr(default=None)

    @property
    def expires_at(self) -> datetime | None:
        if self.idle_ttl > 0:
            if self.absolute_ttl > 0:
                idle_expires = self.last_seen_at + timedelta(minutes=self.idle_ttl)
                absolute_expires = self.created_at + timedelta(
                    minutes=self.absolute_ttl
                )
                return min(idle_expires, absolute_expires)
            else:
                return self.last_seen_at + timedelta(minutes=self.idle_ttl)
        elif self.absolute_ttl > 0:
            return self.created_at + timedelta(minutes=self.absolute_ttl)
        else:
            return None

    @property
    def is_alive(self) -> bool:
        now = datetime.now().astimezone()
        expires_at = self.expires_at
        if expires_at is not None and now > expires_at:
            return False
        self.last_seen_at = now
        return True


class LocalVaultBackend:
    file_name_template: str = "vaults/{username}.json"

    def __init__(
        self,
        base_path: Path,
        iterations: int = 600_000,
        idle_ttl: int = 60,
        absolute_ttl: int = 1440,
        file_name_template: str | None = None,
    ):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.iterations = iterations
        self.idle_ttl = idle_ttl
        self.absolute_ttl = absolute_ttl
        self._sessions: dict[str, LocalVaultSession] = {}

        if file_name_template is not None:
            self.file_name_template = file_name_template

    # -- internal helpers ---------------------------------------------

    def _vault_path(self, username: str) -> Path:
        file_name = self.file_name_template.format(username=username).strip()
        while file_name.startswith("/"):
            file_name = file_name[1:]
        return self.base_path / file_name

    def _derive_key(self, password: str, salt: bytes, iterations: int) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def _load_vault(self, username: str) -> LocalVault:
        path = self._vault_path(username)
        if not path.exists():
            raise ConfigException(f"Vault for user '{username}' does not exist")
        return LocalVault.model_validate_json(path.read_text())

    def _save_vault(self, vault: LocalVault):
        self._vault_path(vault.username).write_text(vault.model_dump_json())

    def _get_session(self, token: str) -> LocalVaultSession:
        session = self._sessions.get(token)
        if session is None or not session.is_alive:
            self._sessions.pop(token, None)
            raise ConfigException("Invalid or expired token")
        return session

    def _decrypt_keys(self, session: LocalVaultSession) -> dict[str, str]:
        if not session.vault.data:
            return {}
        return json.loads(session._fernet.decrypt(session.vault.data.encode()).decode())

    def _encrypt_keys(self, session: LocalVaultSession, keys: dict[str, str]):
        session.vault.data = session._fernet.encrypt(json.dumps(keys).encode()).decode()
        self._save_vault(session.vault)

    # -- SecurityBackend protocol ---------------------------------------

    def create_vault(self, username: str, password: str):
        path = self._vault_path(username)
        if path.exists():
            raise ConfigException(f"Vault for user '{username}' already exists")

        salt = secrets.token_bytes(16)
        key = self._derive_key(password, salt, self.iterations)
        fernet = Fernet(key)

        vault = LocalVault(
            username=username,
            salt=base64.urlsafe_b64encode(salt).decode(),
            iterations=self.iterations,
            verifier=fernet.encrypt(_VERIFIER_PLAINTEXT).decode(),
            data=fernet.encrypt(json.dumps({}).encode()).decode(),
        )
        self._save_vault(vault)

    def drop_vault(self, username: str, password: str):
        # Confirms the password is correct before deleting anything.
        token = self.open_vault(username, password)
        self._sessions.pop(token, None)
        self._vault_path(username).unlink(missing_ok=True)

        # Invalidate any other open sessions for this vault.
        stale = [t for t, s in self._sessions.items() if s.vault.username == username]
        for t in stale:
            self._sessions.pop(t, None)

    def change_vault_password(
        self, username: str, old_password: str, new_password: str
    ):
        token = self.open_vault(username, old_password)
        session = self._sessions.pop(token)
        keys = self._decrypt_keys(session)

        salt = secrets.token_bytes(16)
        new_key = self._derive_key(new_password, salt, self.iterations)
        new_fernet = Fernet(new_key)

        vault = session.vault
        vault.salt = base64.urlsafe_b64encode(salt).decode()
        vault.iterations = self.iterations
        vault.verifier = new_fernet.encrypt(_VERIFIER_PLAINTEXT).decode()
        vault.data = new_fernet.encrypt(json.dumps(keys).encode()).decode()
        self._save_vault(vault)

        # Invalidate every existing session for this vault; caller must
        # open_vault again with the new password.
        stale = [t for t, s in self._sessions.items() if s.vault.username == username]
        for t in stale:
            self._sessions.pop(t, None)

    def open_vault(self, username: str, password: str) -> str:
        vault = self._load_vault(username)
        salt = base64.urlsafe_b64decode(vault.salt)
        key = self._derive_key(password, salt, vault.iterations)
        fernet = Fernet(key)

        try:
            fernet.decrypt(vault.verifier.encode())
        except InvalidToken:
            raise ConfigException("Invalid username or password")

        token = secrets.token_urlsafe(32)
        session = LocalVaultSession(
            token=token,
            vault=vault,
            vault_path=self._vault_path(username),
            idle_ttl=self.idle_ttl,
            absolute_ttl=self.absolute_ttl,
        )
        session._fernet = fernet
        self._sessions[token] = session
        return token

    def close_vault(self, token: str):
        if token in self._sessions:
            self._sessions[token]._fernet = None
            del self._sessions[token]

    def is_token_valid(self, token: str) -> bool:
        session = self._sessions.get(token)
        if session is None:
            return False
        if not session.is_alive:
            self._sessions.pop(token, None)
            return False
        return True

    def list_key_names(self, token: str) -> list[str]:
        session = self._get_session(token)
        return list(self._decrypt_keys(session).keys())

    def load_key(self, token: str, key_name: str) -> str:
        session = self._get_session(token)
        keys = self._decrypt_keys(session)
        if key_name not in keys:
            raise ConfigException(f"Key '{key_name}' not found")
        return keys[key_name]

    def store_key(self, token: str, key_name: str, key_value: str) -> str:
        session = self._get_session(token)
        keys = self._decrypt_keys(session)
        keys[key_name] = key_value
        self._encrypt_keys(session, keys)
        return key_name

    def drop_key(self, token: str, key_name: str):
        session = self._get_session(token)
        keys = self._decrypt_keys(session)
        if key_name not in keys:
            raise ConfigException(f"Key '{key_name}' not found")
        del keys[key_name]
        self._encrypt_keys(session, keys)

    def get_metadata(
        self, token: str, metadata_key: str | None = None
    ) -> dict[str, str] | str:
        session = self._get_session(token)
        if metadata_key is None:
            return dict(session.vault.metadata)
        if metadata_key not in session.vault.metadata:
            raise ConfigException(f"Metadata key '{metadata_key}' not found")
        return session.vault.metadata[metadata_key]

    def set_metadata(self, token: str, metadata_key: str, metadata_value: str):
        session = self._get_session(token)
        session.vault.metadata[metadata_key] = metadata_value
        self._save_vault(session.vault)
