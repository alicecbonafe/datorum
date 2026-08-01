from copy import copy
from cryptography.fernet import Fernet, InvalidToken
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from datorum.model.base import BaseDatorumModel, BaseDatorumPersistentModel
from datorum.model.config import (
    KeyStore,
    KeyStoreException,
    NoKeyStore,
    OSKeychainStore,
    EncryptedFileStore,
    AIServiceProvider,
    AgentRole,
    GeneralConfig,
)
from datorum.exceptions import InvalidIdentifierException


class MockedPersistentModel(BaseDatorumPersistentModel):

    keystore: OSKeychainStore | EncryptedFileStore | None = None

def test_keystore():
    keystore = KeyStore(type="dummy")

    assert not keystore._unlocked

    error_ok = False
    try:
        keystore._ensure_unlocked()
    except KeyStoreException:
        error_ok = True
    assert error_ok

    keystore.unlock()
    assert keystore._unlocked

    error_ok = False
    try:
        keystore.load_key("test")
    except NotImplementedError:
        error_ok = True
    assert error_ok

    error_ok = False
    try:
        keystore.store_key("test", "secret")
    except NotImplementedError:
        error_ok = True
    assert error_ok

def test_no_keystore():
    no_keystore = NoKeyStore()

    error_ok = False
    try:
        no_keystore.unlock()
    except KeyStoreException:
        error_ok = True
    assert error_ok

    error_ok = False
    try:
        no_keystore.load_key("test")
    except KeyStoreException:
        error_ok = True
    assert error_ok

    error_ok = False
    try:
        no_keystore.store_key("test", "secret")
    except KeyStoreException:
        error_ok = True
    assert error_ok

def test_os_keychain_store(mocker: MockerFixture):
    service = "mocked_keychain_service"
    provider_id = "mocked_provider"
    api_key = "***secret***"

    store = OSKeychainStore(service=service)

    mock_set = mocker.patch("keyring.set_password")
    store.store_key(provider_id=provider_id, api_key=api_key)
    mock_set.assert_called_once_with(service, provider_id, api_key)
    
    mock_get = mocker.patch("keyring.get_password", return_value=api_key)
    api_key2 = store.load_key(provider_id=provider_id)
    mock_get.assert_called_once_with(service, provider_id)
    assert api_key == api_key2
    
    mock_get_error = mocker.patch("keyring.get_password", return_value=None)
    error_ok = False
    try:
        store.load_key(provider_id=provider_id)
    except KeyStoreException:
        error_ok = True
    mock_get_error.assert_called_once_with(service, provider_id)
    assert error_ok

def test_encrypted_file_store(tmp_path: Path, mocker: MockerFixture):
    workspace_path = tmp_path / "workspace"
    settings_dir = "mocked_settings"
    persistent_file = "mocked.yml"
    encrypted_file = "encrypted.json"
    provider_id = "mocked_provider"
    encrypted_key = "file-secret"
    api_key = "***secret***"

    store = EncryptedFileStore(
        encrypted_file=encrypted_file,
    )
    MockedPersistentModel(
        keystore=store,
    ).save_as(
        workspace_path=workspace_path,
        settings_dir=settings_dir,
        persisted_file=persistent_file
    )
    parent = MockedPersistentModel.load(
        workspace_path=workspace_path,
        settings_dir=settings_dir,
        persisted_file=persistent_file
    )
    assert parent.keystore.encrypted_path.parent.parent == workspace_path
    assert str(parent.keystore.encrypted_path).endswith(encrypted_file)

    assert not store._unlocked
    store.unlock(password_provider = lambda message: encrypted_key)
    assert store._unlocked
    store.unlock()

    error_ok = False
    try:
        store.load_key(provider_id=provider_id)
    except KeyStoreException:
        error_ok = True
    assert error_ok

    store.store_key(provider_id=provider_id, api_key=api_key)

    file_content = store.encrypted_path.read_text(encoding="utf-8")
    assert "salt" in file_content
    assert "data" in file_content
    assert api_key not in file_content

    api_key_readed = store.load_key(provider_id=provider_id)
    assert api_key_readed == api_key

    error_ok = False
    def password_error_provider(key: str) -> str:
        raise Exception()
    store._unlocked = False
    with pytest.raises(KeyStoreException, match=r"^Could not obtain.*$"):
        store.unlock(password_error_provider)

    error_ok = False
    def password_empty_provider(key: str) -> str:
        return ""
    store._unlocked = False
    with pytest.raises(KeyStoreException, match="Key store password cannot be empty"):
        store.unlock(password_empty_provider)

    mocker.patch.object(
        store._fernet,
        'decrypt',
        side_effect=InvalidToken("Mocked error")
    )
    store._unlocked = True
    with pytest.raises(KeyStoreException, match="Wrong password, or the key store file is corrupted"):
        store._load()

def test_ai_service_provider(tmp_path: Path, mocker: MockerFixture):
    provider_id = "mocked-provider"
    base_url = "http://mocked.local/v1"
    description = "Mocked provider description"
    default_model = "mocked-model-1"
    models = ["mocked-model-2", default_model]
    api_key = "***secret***"

    provider = AIServiceProvider(
        id=provider_id,
        base_url=base_url,
        description=description,
        default_model=default_model,
        models=models
    )
    config = GeneralConfig(
        providers=[provider],
    )

    mocked = mocker.patch.object(
        type(config.key_store),
        "store_key"
    )
    provider.api_key = api_key
    mocked.assert_called_once_with(provider_id, api_key)

    mocked = mocker.patch.object(
        type(config.key_store),
        "load_key",
        return_value=api_key,
    )
    provider._resolved_key = None
    resolved = provider.api_key
    mocked.assert_called_once_with(provider_id)
    assert resolved == api_key

    provider2 = AIServiceProvider(
        id=f"{provider_id}-2",
        base_url=base_url,
        description=description,
        default_model=default_model,
        models=models
    )
    provider2._persistent = BaseDatorumPersistentModel()
    with pytest.raises(ValueError, match="Config not found"):
        config = provider2.config

    with pytest.raises(InvalidIdentifierException, match=r"^default_model '.*?' not in provider '.*?' models list$"):
        AIServiceProvider(
            id=f"{provider_id}-2",
            base_url=base_url,
            description=description,
            default_model=default_model,
            models=["anything", "but", "the", "default", "module"]
        )

def test_general_config(tmp_path: Path):
    provider_1 = AIServiceProvider(
        id="provider-1",
        base_url="http://fake.url/v1",
        description="Mocked Provider 1"
    )
    provider_2 = AIServiceProvider(
        id="provider-2",
        base_url="http://fake.url/v1",
        description="Mocked Provider 2"
    )
    role_1 = AgentRole(
        id="role-1",
        description="Mocked Role 1",
    )
    role_2 = AgentRole(
        id="role-2",
        description="Mocked Role 2",
    )

    config = GeneralConfig(
        providers = [provider_1, provider_2],
        roles = [role_1, role_2],
    )

    assert config.get_provider(provider_1.id) is provider_1
    assert config.get_provider(provider_2.id) is provider_2
    assert config.get_role(role_1.id) is role_1
    assert config.get_role(role_2.id) is role_2

    with pytest.raises(InvalidIdentifierException, match=r"^No provider with id '.*?'$"):
        config.get_provider("unknown-provider")
    with pytest.raises(InvalidIdentifierException, match=r"^No role with id '.*?'$"):
        config.get_role("unknown-role")

    provider_1_copy_1 = copy(provider_1)
    provider_1_copy_2 = copy(provider_1)
    with pytest.raises(InvalidIdentifierException, match=r"^Duplicate child IDs found in 'GeneralConfig.providers':.*?$"):
        GeneralConfig(
            providers=[
                provider_1,
                provider_1_copy_1,
                provider_1_copy_2,
            ]
        )
