from enum import Enum
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, PrivateAttr, model_validator

from .exceptions import SettingsError


class DatorumDumper(yaml.SafeDumper): ...


def represent_path(dumper, path):
    return dumper.represent_str(str(path))


def represent_enum(dumper, enum_value):
    return dumper.represent_data(enum_value.value)


yaml.add_multi_representer(Path, represent_path, Dumper=DatorumDumper)
yaml.add_multi_representer(Enum, represent_enum, Dumper=DatorumDumper)


class BaseDatorumSettings(BaseModel):
    """Base class for Datorum settings.
    
    Provides recursive persistence tracking across nested settings models.
    
    :raises SettingsError: Raised when accessing persistent context before set.
    """

    _persistent: BaseDatorumPersistentSettings | None = PrivateAttr(default=None)

    @property
    def persistent(self) -> BaseDatorumPersistentSettings:
        if self._persistent is None:
            raise SettingsError("Persistent model not defined")
        return self._persistent

    @property
    def settings_path(self) -> Path:
        return self.persistent.settings_path

    def _set_persistent_recursive(
        self,
        persistent_instance: BaseDatorumPersistentSettings,
        visited: set | None = None,
    ) -> None:
        if visited is None:
            visited = set()
        obj_id = id(self)
        if obj_id in visited:
            return
        visited.add(obj_id)

        self._persistent = persistent_instance

        for field_name in self.__class__.model_fields:
            value = getattr(self, field_name)
            self._propagate_persistent(
                value=value,
                persistent_instance=persistent_instance,
                visited=visited,
            )

    def _set_persistent_recursive_in_list(
        self,
        data: list,
        persistent_instance: BaseDatorumPersistentSettings,
        visited: set,
    ) -> None:
        obj_id = id(data)
        if obj_id in visited:
            return
        visited.add(obj_id)

        for value in data:
            self._propagate_persistent(
                value=value,
                persistent_instance=persistent_instance,
                visited=visited,
            )

    def _set_persistent_recursive_in_dict(
        self,
        data: dict,
        persistent_instance: BaseDatorumPersistentSettings,
        visited: set,
    ) -> None:
        obj_id = id(data)
        if obj_id in visited:
            return
        visited.add(obj_id)

        for value in data.values():
            self._propagate_persistent(
                value=value,
                persistent_instance=persistent_instance,
                visited=visited,
            )

    def _propagate_persistent(
        self,
        value: Any,
        persistent_instance: BaseDatorumPersistentSettings,
        visited: set,
    ) -> None:
        if value is None:
            return
        if isinstance(value, BaseDatorumSettings):
            value._set_persistent_recursive(
                persistent_instance=persistent_instance, visited=visited
            )
        elif isinstance(value, list):
            self._set_persistent_recursive_in_list(
                data=value, persistent_instance=persistent_instance, visited=visited
            )
        elif isinstance(value, dict):
            self._set_persistent_recursive_in_dict(
                data=value, persistent_instance=persistent_instance, visited=visited
            )


class BaseDatorumPersistentSettings(BaseDatorumSettings):
    """Base class for Datorum persistent settings.

    Handles loading, saving, and path resolution for top-level settings objects.

    :param settings_path: Path to the underlying YAML file.
    :type settings_path: pathlib.Path
    :raises SettingsError: If the settings file is missing or invalid.
    """

    _settings_path: Path | None = PrivateAttr(default=None)

    @property
    def settings_path(self) -> Path:
        if self._settings_path is None:
            if self.persistent is self:
                raise SettingsError("Settings file path not defined.")
            return self.persistent.settings_path
        return self._settings_path

    @settings_path.setter
    def settings_path(self, value: Path):
        self._settings_path = value

    @classmethod
    def load(cls, settings_path: Path) -> Self:
        """Loads settings from a file."""
        if not settings_path.exists():
            raise SettingsError(f"Settings file not found: {settings_path}")

        with settings_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        instance = cls.model_validate(data)
        instance.settings_path = settings_path
        return instance

    def save_as(self, settings_path: Path):
        """Changes the settings path and save the file."""
        self.settings_path = settings_path
        if self.persistent is not self:
            self._set_persistent_recursive(self)
        self.save()

    def save(self):
        """Saves the settings file. If this object belongs to another persistent model, calls its save method and returns."""
        if self.persistent is not self:
            self.persistent.save()
            return

        data = self.model_dump(mode="python")
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        with self.settings_path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, sort_keys=False, Dumper=DatorumDumper)

    def reload(self):
        """Reloads settings from file."""
        if self.persistent is not self:
            self.persistent.reload()
            return

        if not self.settings_path.exists():
            raise SettingsError(f"Settings file not found: {self.settings_path}")

        with self.settings_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        updated_instance = self.__class__.model_validate(data)
        self.__dict__.update(updated_instance.__dict__)
        self._set_persistent_recursive(self)

    @model_validator(mode="after")
    def _root_model(self) -> BaseDatorumPersistentSettings:
        self._set_persistent_recursive(self)
        return self
