from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, PrivateAttr, model_validator
import yaml

from ..exceptions import NoFilePathException, ConfigException


class DatorumDumper(yaml.SafeDumper): ...

def represent_path(dumper, path):
    return dumper.represent_str(str(path))

yaml.add_multi_representer(Path, represent_path, Dumper=DatorumDumper)


class BaseDatorumModel(BaseModel):

    _persistent: Optional["BaseDatorumPersistentModel"] = PrivateAttr(default=None)

    @property
    def persistent(self) -> "BaseDatorumPersistentModel":
        if self._persistent is None:
            raise ConfigException("Persistent model not defined")
        return self._persistent

    @property
    def workspace_path(self) -> Path:
        return self.persistent.workspace_path

    @property
    def settings_path(self) -> Path:
        return self.persistent.settings_path

    @property
    def persisted_path(self) -> Path:
        return self.persistent.persisted_path

    def _set_persistent_recursive(
        self,
        persistent_instance: "BaseDatorumPersistentModel",
        visited: set | None = None,
    ) -> None:
        if visited is None:
            visited = set()
        obj_id = id(self)
        if obj_id in visited:
            return
        visited.add(obj_id)

        self._persistent = persistent_instance

        for field_name, _ in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            self._propagate_persistent(
                value=value,
                persistent_instance=persistent_instance,
                visited=visited,
            )

    def _set_persistent_recursive_in_list(
        self,
        data: list,
        persistent_instance: "BaseDatorumPersistentModel",
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
        persistent_instance: "BaseDatorumPersistentModel",
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
        value: any,
        persistent_instance: "BaseDatorumPersistentModel",
        visited: set | None = None,
    ) -> None:
        if value is None:
            return
        if isinstance(value, BaseDatorumModel):
            value._set_persistent_recursive(
                persistent_instance=persistent_instance,
                visited=visited
            )
        elif isinstance(value, list):
            self._set_persistent_recursive_in_list(
                data=value,
                persistent_instance=persistent_instance,
                visited=visited
            )
        elif isinstance(value, dict):
            self._set_persistent_recursive_in_dict(
                data=value,
                persistent_instance=persistent_instance,
                visited=visited
            )


class BaseDatorumPersistentModel(BaseDatorumModel):

    _workspace_path: Path | None = PrivateAttr(default=None)
    _settings_dir: str | None = PrivateAttr(default=None)
    _persisted_file: str | None = PrivateAttr(default=None)

    @classmethod
    def load(cls, workspace_path: Path, persisted_file: str, settings_dir: str = ".datorum") -> 'BaseDatorumPersistentModel':
        file_path = workspace_path / settings_dir / persisted_file
        with file_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        instance = cls.model_validate(data)
        instance._workspace_path = workspace_path
        instance._settings_dir = settings_dir
        instance._persisted_file = persisted_file
        return instance

    @property
    def workspace_path(self) -> Path:
        if self._workspace_path is None:
            if self._persistent and self.persistent is not self:
                return self.persistent.workspace_path
            raise NoFilePathException("No file path defined for this object.")
        return self._workspace_path

    @property
    def settings_path(self) -> Path:
        return self.workspace_path / self._settings_dir

    @property
    def persisted_path(self) -> Path:
        return self.settings_path / self._persisted_file

    def save_as(self, workspace_path: Path, persisted_file: str, settings_dir: str = ".datorum"):
        self._workspace_path = workspace_path
        self._settings_dir = settings_dir
        self._persisted_file = persisted_file
        self.save()

    def save(self):
        data = self.model_dump(mode="python")
        self.settings_path.mkdir(parents=True, exist_ok=True)
        with self.persisted_path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, sort_keys=False, Dumper=DatorumDumper)

    @model_validator(mode="after")
    def _root_model(self) -> "BaseDatorumPersistentModel":
        self._set_persistent_recursive(self)
        return self
