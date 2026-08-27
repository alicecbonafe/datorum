from pydantic import Field

from ..binding.settings import ContextBind, ResourceBind
from ..core.settings import BaseDatorumPersistentSettings, BaseDatorumSettings


class ToolBoxSetUp(BaseDatorumSettings):
    """Settings for the materialization of a toolbox with bindings for resources and contexts.
    
    This class holds some fixed definitions for a `ToolBoxDefinition` such as which
    tools are enabled and predefined binds, useful for configuration data and document
    templates.
    """

    id: str = Field(description="Toolbox setup identifier.")
    toolbox_name: str = Field(description="Name of the registered `ToolBox` this setup materializes.")

    tools_enabled: list[str] = Field(
        default_factory=list,
        description="Names of the tools enabled for this setup.",
    )

    context_bindings: list[ContextBind] = Field(
        default_factory=list,
        description="Predefined context bindings for this setup's fields.",
    )
    resource_bindings: list[ResourceBind] = Field(
        default_factory=list,
        description="Predefined resource bindings for this setup's fields.",
    )

    active_tool: str | None = Field(
        default=None,
        exclude=True,
        description="Tool currently selected for execution on this setup instance (not persisted).",
    )


class ToolKit(BaseDatorumPersistentSettings):
    """Persistent settings class storing available toolbox setups."""

    toolboxes: dict[str, ToolBoxSetUp] = Field(
        default_factory=dict,
        description="Available toolbox setups, keyed by setup ID.",
    )
