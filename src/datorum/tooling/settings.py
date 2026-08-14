from typing import Optional

from pydantic import Field

from ..context.settings import ContextBindType, ResourceBind
from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class ToolBoxSetUp(BaseDatorumSettings):
    id: str
    toolbox_name: str

    tools_enabled: list[str] = Field(default_factory=list)

    context_bindings: dict[str, str] = Field(default_factory=dict)
    resource_bindings: dict[str, ResourceBind] = Field(default_factory=dict)

    active_tool: Optional[str] = Field(default=None, exclude=True)


class ToolKit(BaseDatorumPersistentSettings):
    toolboxes: list[ToolBoxSetUp] = Field(default_factory=list)

