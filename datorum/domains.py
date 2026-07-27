import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Generator

from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    field_validator,
    model_validator
)
import yaml

from . import GeneralConfig


DOMAIN_DELIMITER = '.'


class BaseNode(BaseModel):

    id: str
    name: str | None = None
    description: str | None = None
    metadata: Dict[str, str] = Field(default_factory=dict)

    _parent: Optional['Domain'] = PrivateAttr(default=None)

    @property
    def parent(self) -> Optional['Domain']:
        return self._parent

    @field_validator('id')
    @classmethod
    def validate_delimiter(cls, v: str) -> str:
        if DOMAIN_DELIMITER in v:
            raise ValueError(f"ID '{v}' cannot contain [{DOMAIN_DELIMITER}]")
        return v


class Source(BaseNode):

    url: str | None = None
    source_file: str | None = None
    chunks_file: str | None = None
    scraper: str | None = None
    scraper_args: Dict[str, Any] = Field(default_factory=dict)


class Domain(BaseNode):

    domains: List['Domain'] = Field(default_factory=list)
    sources: List['Source'] = Field(default_factory=list)

    def get_child(self, child_id: str) -> Optional[BaseNode]:
        for child in self.domains + self.sources:
            if child.id == child_id:
                return child
        return None

    def get(self, path: str) -> Optional[BaseNode]:
        if not path:
            return self

        parts = path.split(DOMAIN_DELIMITER, 1)
        current_id = parts[0]
        rest_of_path = parts[1] if len(parts) > 1 else None

        child = self.get_child(current_id)
        if child is None or rest_of_path is None:
            return child
        if isinstance(child, Domain):
            return child.get(rest_of_path)
        return None

    def __getitem__(self, path: str) -> BaseNode:
        node = self.get(path)
        if node is None:
            raise KeyError(f'Node "{path}" not found in domain "{self.id}".')
        return node

    def __contains__(self, path: str) -> bool:
        return self.get(path) is not None

    def walk(self) -> Generator[BaseNode, None, None]:
        for domain in self.domains:
            yield domain
            yield from domain.walk()
        for source in self.sources:
            yield source

    @model_validator(mode='after')
    def validate_unique_child_ids(self) -> 'Domain':
        child_ids = [domain.id for domain in self.domains]
        child_ids.extend([source.id for source in self.sources])
        if len(child_ids) != len(set(child_ids)):
            # Identify duplicates to provide a clearer error message
            from collections import Counter
            duplicates = [id for id, count in Counter(child_ids).items() if count > 1]
            raise ValueError(f"Duplicate child IDs found: {duplicates}")
        return self

    @model_validator(mode='after')
    def _post_init_setup(self) -> 'Domain':
        # 1. Valida IDs duplicados no mesmo nível
        child_ids = [d.id for d in self.domains] + [s.id for s in self.sources]
        if len(child_ids) != len(set(child_ids)):
            from collections import Counter
            duplicates = [id for id, count in Counter(child_ids).items() if count > 1]
            raise ValueError(f"Duplicate child IDs found in '{self.id}': {duplicates}")

        # 2. Amarra referências de pai aos filhos automaticamente
        for domain in self.domains:
            domain._parent = self
        for source in self.sources:
            source._parent = self

        return self

class DomainCollection(Domain):

    sources_path: str = Field(default='sources')
    chunks_path: str = Field(default='chunks')

    @classmethod
    def load(cls, file_path: Optional[str|Path] = None):
        if file_path is None:
            file_path = Path(GeneralConfig.get('DATA_DIR', 'data')) / 'domains.yml'
        elif type(file_path) == str:
            file_path = Path(file_path)

        with file_path.open('r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def save(self, file_path: Optional[str|Path] = None):
        if file_path is None:
            file_path = Path(GeneralConfig.get('DATA_DIR', 'data')) / 'domains.yml'
        elif type(file_path) == str:
            file_path = Path(file_path)

        data = self.model_dump(mode="python")
        print(data)
        with file_path.open('w', encoding='utf-8') as f:
            yaml.safe_dump(data, f, sort_keys=False)
