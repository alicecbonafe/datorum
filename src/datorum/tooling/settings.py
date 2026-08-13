import inspect
from collections.abc import Callable
import types
from typing import (
    Any,
    Literal,
    Protocol,
    Optional,
    Self,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    runtime_checkable,
)

from pydantic import BaseModel, Field, PrivateAttr, create_model

from .binding import ContextBindType
from .context import DocumentContext
from .exceptions import ToolBoxException
from .settings import BaseDatorumPersistentSettings, BaseDatorumSettings

# ======================================================
# | Settings
# ======================================================


class ToolBoxSetUp(BaseDatorumSettings):
    id: str
    toolbox_name: str

    tools_enabled: list[str] = Field(default_factory=list)

    context_bindings: dict[str, str] = Field(default_factory=dict)
    resource_bindings: dict[str, ResourceBind] = Field(default_factory=dict)

    active_tool: Optional[str] = Field(default=None, exclude=True)


class ToolBoxCollection(BaseDatorumPersistentSettings):
    toolboxes: list[ToolBoxSetUp] = Field(default_factory=list)

