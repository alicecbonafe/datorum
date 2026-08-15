from typing import Optional

from pydantic import Field

from ..context.settings import ContextBindType, ResourceBind
from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class ToolBoxSetUp(BaseDatorumSettings):
    id: str
    toolbox_name: str

    tools_enabled: list[str] = Field(default_factory=list)

    context_bindings: list[ContextBindType] = Field(default_factory=list)
    resource_bindings: list[ResourceBind] = Field(default_factory=list)

    active_tool: Optional[str] = Field(default=None, exclude=True)


class ToolKit(BaseDatorumPersistentSettings):
    toolboxes: dict[str, ToolBoxSetUp] = Field(default_factory=dict)
