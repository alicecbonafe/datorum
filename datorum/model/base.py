from pathlib import Path

from pydantic import BaseModel, Field, PrivateAttr
import yaml

from ..exceptions import NoFilePathException


class DatorumDumper(yaml.SafeDumper): ...

def represent_path(dumper, path):
    return dumper.represent_str(str(path))

yaml.add_multi_representer(Path, represent_path, Dumper=DatorumDumper)


class BaseDatorumModel(BaseModel): ...


class BaseDatorumPersistentModel(BaseDatorumModel):

    _filepath: Path | None = PrivateAttr(default=None)

    @classmethod
    def load(cls, filepath: str | Path) -> 'BaseDatorumPersistentModel':
        if not isinstance(filepath, Path):
            filepath = Path(filepath)

        with filepath.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        instance = cls.model_validate(data)
        instance._filepath = filepath
        return instance

    @property
    def filepath(self) -> Path:
        if self._filepath is None:
            raise NoFilePathException("No file path defined for this object.")
        return self._filepath

    def save(self, filepath: str | Path | None = None):
        if filepath is not None:
            if not isinstance(filepath, Path):
                filepath = Path(filepath)
            self._filepath = filepath

        data = self.model_dump(mode="python")

        with self.filepath.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, sort_keys=False, Dumper=DatorumDumper)
