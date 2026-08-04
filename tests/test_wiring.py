import pytest

from datorum.wiring import (
    ResourceFactoryRegistry,
    get_resource,
    register_resource_factory,
    resource_factory,
)


@pytest.mark.depends(on=["tests/test_base_settings.py"])
def test_registry():
    resource_1_id = "mocked_resource_1"
    resource_2_id = "mocked_resource_2"
    target_alias = "mocked_target"

    def mocked_factory_1(param: str):
        return f"({param})"

    register_resource_factory(resource_id=resource_1_id, factory=mocked_factory_1)

    assert ResourceFactoryRegistry[resource_1_id] == mocked_factory_1
    assert get_resource(
        resource_id=resource_1_id, target_alias=target_alias
    ) == mocked_factory_1(target_alias)

    @resource_factory(resource_2_id)
    def mocked_factory_2(param: str):
        return f"[{param}]"

    assert ResourceFactoryRegistry[resource_2_id] == mocked_factory_2
    assert get_resource(
        resource_id=resource_2_id, target_alias=target_alias
    ) == mocked_factory_2(target_alias)
