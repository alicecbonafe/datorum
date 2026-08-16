import os
import re
from collections.abc import Mapping
from typing import Callable, Protocol

from .exceptions import InvalidKeyNameError, KeyNotFoundError


class SecurityBackend(Protocol):
    def get_key(self, key_name: str) -> str: ...

class EnvVarBackend:
    key_name_re: re.Pattern[str] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(self,
        source: Mapping[str, str] = os.environ,
        *,
        key_name_match: str | None = None,
        key_name_formatter: Callable[[str], str] | None = None,
    ):
        self.source: Mapping[str, str] = source
        self.key_name_formatter: Callable[[str], str] | None = key_name_formatter
        if key_name_match:
            self.key_name_re: re.Pattern[str] = re.compile(key_name_match)

    def get_key(self, key_name: str) -> str:
        formatted_name = self.key_name_formatter(key_name) \
            if self.key_name_formatter else key_name

        if not self.key_name_re.match(formatted_name):
            raise InvalidKeyNameError(
                f"Key '{key_name}' is not a valid environment variable name (formatted as '{formatted_name}')"
            )
        try:
            return self.source[formatted_name]
        except KeyError:
            raise KeyNotFoundError(f"Key '{key_name}' is not set (formatted as '{formatted_name}')") from None


