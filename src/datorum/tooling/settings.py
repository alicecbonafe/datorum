
from pydantic import Field

from ..binding.settings import ContextBindType, ResourceBind
from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class ToolBoxSetUp(BaseDatorumSettings):
    id: str
    toolbox_name: str

    tools_enabled: list[str] = Field(default_factory=list)

    context_bindings: list[ContextBindType] = Field(default_factory=list)
    resource_bindings: list[ResourceBind] = Field(default_factory=list)

    active_tool: str | None = Field(default=None, exclude=True)


class ToolKit(BaseDatorumPersistentSettings):
    toolboxes: dict[str, ToolBoxSetUp] = Field(default_factory=dict)
