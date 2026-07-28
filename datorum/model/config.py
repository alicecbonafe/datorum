from pathlib import Path

from pydantic import Field, PrivateAttr

from .base import BaseDatorumPersistentModel




class GeneralConfig(BaseDatorumPersistentModel):

    data_dir: Path = Field(description="Path for the data directory")
    log_file: Path | None = Field(default=None, description="Path for the log file")


