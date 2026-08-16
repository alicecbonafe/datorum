import os
import re
from collections.abc import Mapping, Callable

from .registry import resource, ResourceFactoryRegistry
from .exceptions import KeyNotFoundError, InvalidKeyNameError


DEFAULT_KEY_NAME_MATCH = r"^[A-Za-z_][A-Za-z0-9_]*$"

def register_mapped_api_key_factory(
    source: Mapping[str, str] = os.environ,
    *,
    key_name_match: str | None = None,
    key_name_formatter: Callable[[str], str] | None = None,
    force: bool = False,
):
    if not force and "api_key" in ResourceFactoryRegistry:
        return

    key_name_re: re.Pattern[str] = re.compile(key_name_match or DEFAULT_KEY_NAME_MATCH)

    @resource(name="api_key", force=True)
    def _api_key(key_name):
        formatted_name = key_name_formatter(key_name) \
            if key_name_formatter else key_name

        if not key_name_re.match(formatted_name):
            raise InvalidKeyNameError(
                f"Key '{key_name}' is not a valid environment variable name (formatted as '{formatted_name}')"
            )
        try:
            return source[formatted_name]
        except KeyError:
            raise KeyNotFoundError(f"Key '{key_name}' is not set (formatted as '{formatted_name}')") from None

