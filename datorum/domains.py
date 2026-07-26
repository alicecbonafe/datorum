import os
from pathlib import Path
from typing import List, Dict, Set, Any, Optional

from pydantic import (
    BaseModel,
    Field,
    # TypeAdapter,
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

    @field_validator('id')
    @classmethod
    def validate_delimiter(cls, v: str) -> str:
        if DOMAIN_DELIMITER in v:
            raise ValueError(f"ID '{v}' cannot contain [{DOMAIN_DELIMITER}]")
        return v

    def __hash__(self):
        return hash(self.id)


class Source(BaseNode):

    url: str
    source_file: str
    chunks_file: str
    scraper: str
    scraper_args: Dict[str, Any] = Field(default_factory=dict)


class Domain(BaseNode):

    domains: List['Domain'] = Field(default_factory=list)
    sources: List['Source'] = Field(default_factory=list)

    def find_domain(self, domain_id: str) -> 'Domain':
        next_delimiter: int = domain_id.find(DOMAIN_DELIMITER)
        if next_delimiter < 0:
            return self.domains[domain_id]

        current_id = domain_id[0:next_delimiter]
        next_id = domain_id[next_delimiter+len(DOMAIN_DELIMITER):]
        return self.domains[current_id].find_domain(next_id)

    def find_source(self, domain_id: str) -> 'Source':
        next_delimiter: int = domain_id.find(DOMAIN_DELIMITER)
        if next_delimiter < 0:
            return self.sources[domain_id]

        current_id = domain_id[0:next_delimiter]
        next_id = domain_id[next_delimiter+len(DOMAIN_DELIMITER):]
        return self.domains[current_id].find_source(next_id)

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
