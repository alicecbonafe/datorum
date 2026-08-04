from copy import copy
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from datorum.exceptions import InvalidIdentifierException
from datorum.inference import (
    AgentRole,
    AIConfig,
    AIServiceProvider,
)


@pytest.mark.depends(on=["tests/test_base_settings.py"])
def test_ai_service_provider(tmp_path: Path, mocker: MockerFixture):
    provider_id = "mocked-provider"
    base_url = "http://mocked.local/v1"
    description = "Mocked provider description"
    default_model = "mocked-model-1"
    models = ["mocked-model-2", default_model]
    # api_key = "***secret***"

    provider = AIServiceProvider(
        id=provider_id,
        base_url=base_url,
        description=description,
        default_model=default_model,
        models=models
    )
    AIConfig(
        providers=[provider],
    )

    with pytest.raises(InvalidIdentifierException, match=r"^default_model '.*?' not in provider '.*?' models list$"):
        AIServiceProvider(
            id=f"{provider_id}-2",
            base_url=base_url,
            description=description,
            default_model=default_model,
            models=["anything", "but", "the", "default", "module"]
        )

@pytest.mark.depends(on=["test_ai_service_provider"])
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

    config = AIConfig(
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
    with pytest.raises(InvalidIdentifierException, match=r"^Duplicate child IDs found in 'AIConfig.providers':.*?$"):
        AIConfig(
            providers=[
                provider_1,
                provider_1_copy_1,
                provider_1_copy_2,
            ]
        )
