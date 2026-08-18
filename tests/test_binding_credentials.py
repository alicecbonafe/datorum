import pytest

from datorum.binding.binder import Binder
from datorum.binding.credentials import register_mapped_api_key_factory
from datorum.binding.exceptions import InvalidKeyNameError, KeyNotFoundError
from datorum.binding.registry import ResourceFactoryRegistry


@pytest.fixture(autouse=True)
def _isolate_global_resource_registry():
    """`register_mapped_api_key_factory` without an explicit `binder` writes
    into the module-level `ResourceFactoryRegistry` under the fixed name
    'api_key'. Snapshot/restore that single entry around each test so tests
    in this file can't leak state into each other or into the rest of the
    suite."""
    original = ResourceFactoryRegistry.pop("api_key", None)
    yield
    ResourceFactoryRegistry.pop("api_key", None)
    if original is not None:
        ResourceFactoryRegistry["api_key"] = original


def test_register_default_binder_registers_global_factory():
    source = {"MY_KEY": "secret-value"}

    register_mapped_api_key_factory(source=source)

    assert "api_key" in ResourceFactoryRegistry
    factory = ResourceFactoryRegistry["api_key"]
    assert factory("MY_KEY") == "secret-value"


def test_register_skips_when_already_registered_without_force():
    register_mapped_api_key_factory(source={"KEY_ONE": "one"})
    # Second call, different source, force defaults to False: should be a no-op.
    register_mapped_api_key_factory(source={"KEY_ONE": "two"})

    factory = ResourceFactoryRegistry["api_key"]
    assert factory("KEY_ONE") == "one"


def test_register_force_overwrites_existing_global_factory():
    register_mapped_api_key_factory(source={"KEY_ONE": "one"})
    register_mapped_api_key_factory(source={"KEY_ONE": "two"}, force=True)

    factory = ResourceFactoryRegistry["api_key"]
    assert factory("KEY_ONE") == "two"


def test_register_with_binder_uses_binder_local_factories():
    binder = Binder()
    source = {"BINDER_KEY": "binder-value"}

    register_mapped_api_key_factory(source=source, binder=binder)

    assert "api_key" not in ResourceFactoryRegistry
    factory = binder.factories["api_key"]
    assert factory("BINDER_KEY") == "binder-value"


def test_register_with_binder_always_overwrites_regardless_of_force():
    """Internally, the binder path is always decorated with force=True, so
    re-registering against a binder never raises even without passing
    force=True to register_mapped_api_key_factory itself."""
    binder = Binder()
    register_mapped_api_key_factory(source={"KEY_ONE": "one"}, binder=binder)
    register_mapped_api_key_factory(source={"KEY_ONE": "two"}, binder=binder)

    factory = binder.factories["api_key"]
    assert factory("KEY_ONE") == "two"


def test_factory_raises_key_not_found_for_missing_key():
    binder = Binder()
    register_mapped_api_key_factory(source={}, binder=binder)
    factory = binder.factories["api_key"]

    with pytest.raises(KeyNotFoundError, match="MISSING_KEY"):
        factory("MISSING_KEY")


def test_factory_raises_invalid_key_name_for_malformed_key():
    binder = Binder()
    register_mapped_api_key_factory(source={"1BAD": "x"}, binder=binder)
    factory = binder.factories["api_key"]

    with pytest.raises(InvalidKeyNameError, match="1BAD"):
        factory("1BAD")


def test_factory_respects_custom_key_name_match():
    binder = Binder()
    # 'my-key' would fail the DEFAULT_KEY_NAME_MATCH pattern (no dashes
    # allowed), so accepting it here proves the custom pattern is in effect.
    register_mapped_api_key_factory(
        source={"my-key": "value"},
        binder=binder,
        key_name_match=r"^[a-z\-]+$",
    )
    factory = binder.factories["api_key"]

    assert factory("my-key") == "value"


def test_factory_applies_key_name_formatter_before_lookup():
    binder = Binder()
    source = {"PREFIX_MY_KEY": "formatted-value"}

    register_mapped_api_key_factory(
        source=source,
        binder=binder,
        key_name_formatter=lambda name: f"PREFIX_{name}",
    )
    factory = binder.factories["api_key"]

    assert factory("MY_KEY") == "formatted-value"


def test_factory_reports_formatted_name_when_formatter_yields_invalid_name():
    binder = Binder()
    register_mapped_api_key_factory(
        source={},
        binder=binder,
        key_name_formatter=lambda name: f"1{name}",
    )
    factory = binder.factories["api_key"]

    with pytest.raises(InvalidKeyNameError, match=r"formatted as '1KEY'"):
        factory("KEY")


def test_default_source_is_os_environ(monkeypatch):
    monkeypatch.setenv("DATORUM_TEST_ENV_KEY", "env-value")
    binder = Binder()

    register_mapped_api_key_factory(binder=binder)
    factory = binder.factories["api_key"]

    assert factory("DATORUM_TEST_ENV_KEY") == "env-value"