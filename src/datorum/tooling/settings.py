from pydantic import Field

from ..binding.settings import ContextBind, ResourceBind
from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class ToolBoxSetUp(BaseDatorumSettings):
    """Settings for the materialization of a toolbox with bindings for resources and contexts.
    
    This class holds some fixed definitions for a `ToolBoxDefinition` such as which
    tools are enabled and predefined binds, useful for configuration data and document
    templates.
    """

    id: str
    toolbox_name: str

    tools_enabled: list[str] = Field(default_factory=list)

    context_bindings: list[ContextBind] = Field(default_factory=list)
    resource_bindings: list[ResourceBind] = Field(default_factory=list)

    active_tool: str | None = Field(default=None, exclude=True)


class ToolKit(BaseDatorumPersistentSettings):
    """Persistent settings class storing available toolbox setups."""

    toolboxes: dict[str, ToolBoxSetUp] = Field(default_factory=dict)
