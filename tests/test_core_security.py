from datetime import timedelta
from pathlib import Path

import pytest

from datorum.core.exceptions import (
    ConfigException,
)
from datorum.core.security import (
    LocalVaultBackend,
    get_security_backend,
    set_security_backend,
)


class DummyBackend:
    def create_vault(self, username: str, password: str):
        raise NotImplementedError("Dummy BackEnd")

    def drop_vault(self, username: str, password: str):
        raise NotImplementedError("Dummy BackEnd")

    def change_vault_password(
        self, username: str, old_password: str, new_password: str
    ):
        raise NotImplementedError("Dummy BackEnd")

    def open_vault(self, username: str, password: str) -> str:
        raise NotImplementedError("Dummy BackEnd")

    def close_vault(self, token: str):
        raise NotImplementedError("Dummy BackEnd")

    def is_token_valid(self, token: str) -> bool:
        raise NotImplementedError("Dummy BackEnd")

    def list_key_names(self, token: str) -> list[str]:
        raise NotImplementedError("Dummy BackEnd")

    def load_key(self, token: str, key_name: str) -> str:
        raise NotImplementedError("Dummy BackEnd")

    def store_key(self, token: str, key_name: str, key_value: str) -> str:
        raise NotImplementedError("Dummy BackEnd")

    def drop_key(self, token: str, key_name: str):
        raise NotImplementedError("Dummy BackEnd")

    def get_metadata(
        self, token: str, metadata_key: str | None = None
    ) -> dict[str, str] | str:
        raise NotImplementedError("Dummy BackEnd")

    def set_metadata(self, token: str, metadata_key: str, metadata_value: str):
        raise NotImplementedError("Dummy BackEnd")


def test_registry():
    with pytest.raises(ConfigException, match=r"^Security backend not found$"):
        get_security_backend()
    backend = DummyBackend()
    set_security_backend(backend=backend)
    assert get_security_backend() is backend


def test_local_vault(tmp_path: Path):
    username = "mocked.user"
    password = "***secret***"
    password_alt = "***other*secret***"
    key_name = "mocked-provider"
    api_key = "THIS_SHOULD_NOT_BE_VISIBLE_IN_THE_FILE"

    metadata_1_key = "meta_1"
    metadata_1_value = "this is a mocked string"
    metadata_2_key = "meta_2"
    metadata_2_value = "this also is a mocked string"
    metadata_alt_value = "this is the new mocked string"
    metadata_missing_key = "meta_missing"

    local_vault = LocalVaultBackend(
        base_path=tmp_path, file_name_template="/{username}.json"
    )

    local_vault.create_vault(
        username=username,
        password=password,
    )
    assert (tmp_path / f"{username}.json").exists()

    token = local_vault.open_vault(
        username=username,
        password=password,
    )
    assert token
    assert local_vault.is_token_valid(token=token)
    assert len(local_vault.list_key_names(token=token)) == 0

    local_vault.store_key(token=token, key_name=key_name, key_value=api_key)
    assert len(local_vault.list_key_names(token=token)) == 1
    assert api_key not in (tmp_path / f"{username}.json").read_text(encoding="utf-8")

    api_key_loaded = local_vault.load_key(token=token, key_name=key_name)
    assert api_key == api_key_loaded

    local_vault.drop_key(token=token, key_name=key_name)
    assert len(local_vault.list_key_names(token=token)) == 0
    with pytest.raises(ConfigException, match=r"Key '.*?' not found"):
        local_vault.load_key(token=token, key_name=key_name)
    with pytest.raises(ConfigException, match=r"Key '.*?' not found"):
        local_vault.drop_key(token=token, key_name=key_name)

    local_vault.store_key(token=token, key_name=key_name, key_value=api_key)
    assert len(local_vault.list_key_names(token=token)) == 1
    local_vault._sessions[token].vault.data = None
    assert len(local_vault.list_key_names(token=token)) == 0

    assert len(local_vault.get_metadata(token=token)) == 0
    local_vault.set_metadata(
        token=token,
        metadata_key=metadata_1_key,
        metadata_value=metadata_1_value,
    )
    local_vault.set_metadata(
        token=token,
        metadata_key=metadata_2_key,
        metadata_value=metadata_2_value,
    )
    assert len(local_vault.get_metadata(token=token)) == 2
    local_vault.set_metadata(
        token=token,
        metadata_key=metadata_2_key,
        metadata_value=metadata_alt_value,
    )
    assert (
        local_vault.get_metadata(token=token, metadata_key=metadata_2_key)
        == metadata_alt_value
    )

    with pytest.raises(ConfigException, match=r"Metadata key '.*?' not found"):
        local_vault.get_metadata(token=token, metadata_key=metadata_missing_key)

    session_1 = local_vault._sessions[token]
    local_vault.close_vault(token=token)
    assert not local_vault.is_token_valid(token=token)
    with pytest.raises(ConfigException, match="Fernet not found"):
        assert session_1.fernet

    local_vault.idle_ttl = 0
    token = local_vault.open_vault(
        username=username,
        password=password,
    )
    assert local_vault.is_token_valid(token=token)
    local_vault.close_vault(token=token)
    local_vault.absolute_ttl = 0
    token = local_vault.open_vault(
        username=username,
        password=password,
    )
    assert local_vault.is_token_valid(token=token)
    local_vault.close_vault(token=token)
    local_vault.idle_ttl = 60
    token = local_vault.open_vault(
        username=username,
        password=password,
    )
    assert local_vault.is_token_valid(token=token)

    local_vault._sessions[token].last_seen_at -= timedelta(minutes=100)
    assert not local_vault.is_token_valid(token=token)
    with pytest.raises(ConfigException, match="Invalid or expired token"):
        local_vault.list_key_names(token=token)

    local_vault.close_vault(token=token)

    with pytest.raises(ConfigException, match=r"^Vault for user '.*?' already exists$"):
        local_vault.create_vault(
            username=username,
            password=password,
        )

    local_vault.open_vault(
        username=username,
        password=password,
    )
    assert len(local_vault._sessions) == 1
    local_vault.change_vault_password(
        username=username, old_password=password, new_password=password_alt
    )
    assert len(local_vault._sessions) == 0
    with pytest.raises(ConfigException, match="Invalid username or password"):
        local_vault.open_vault(
            username=username,
            password=password,
        )
    local_vault.change_vault_password(
        username=username, old_password=password_alt, new_password=password
    )

    assert len(local_vault._sessions) == 0
    local_vault.open_vault(
        username=username,
        password=password,
    )
    local_vault.open_vault(
        username=username,
        password=password,
    )
    local_vault.open_vault(
        username=username,
        password=password,
    )
    assert len(local_vault._sessions) == 3

    local_vault.drop_vault(
        username=username,
        password=password,
    )
    assert not (tmp_path / f"{username}.json").exists()
    assert len(local_vault._sessions) == 0

    with pytest.raises(ConfigException, match=r"^Vault for user '.*?' does not exist"):
        local_vault.open_vault(
            username=username,
            password=password,
        )
