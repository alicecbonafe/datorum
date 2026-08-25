from pathlib import Path

from pydantic import Field, PrivateAttr, model_validator

import datorum


class CliAppSettings(datorum.BaseDatorumPersistentSettings):
    contexts_path: Path = Field(default_factory=lambda: Path("contexts"))
    flows_path: Path = Field(default_factory=lambda: Path("flows"))
    flow_id_template: str = "flow_{index}"

    toolkit: datorum.ToolKit = Field(default_factory=datorum.ToolKit)
    agencykit: datorum.AgencyKit = Field(default_factory=datorum.AgencyKit)
    plumbingkit: datorum.PlumbingKit = Field(default_factory=datorum.PlumbingKit)

    contexts: dict[str, datorum.DocumentContext] = Field(default_factory=dict)

    custom_registry: list[Path] = Field(default_factory=list)

    api_keys: dict[str, str] | None = None

    _loaded: bool = PrivateAttr(False)

    def load_lazy(self):
        if not self._loaded:
            self.reload()
            self._loaded = True

    @model_validator(mode="after")
    def _inject_path(self) -> CliAppSettings:
        for context_id, context in self.contexts.items():
            context.base_path = self.contexts_path / context_id

        return self
