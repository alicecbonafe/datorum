import re
from collections.abc import Generator
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from .settings_base import BaseDatorumSettings, BaseDatorumPersistentSettings
from .exceptions import InvalidIdentifierException, OrphanSourceException

DOMAIN_DELIMITER = "."
ID_PATTERN = r"^\w+$"


class BaseNode(BaseDatorumSettings):

    id: str
    name: str | None = None
    description: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    _parent: Optional["Domain"] = PrivateAttr(default=None)

    @property
    def parent(self) -> Optional["Domain"]:
        return self._parent

    @property
    def full_id(self) -> str:
        if self.parent is None:
            return self.id
        return f"{self.parent.full_id}{DOMAIN_DELIMITER}{self.id}"

    @property
    def root(self) -> "BaseNode":
        return self if self.parent is None else self.parent.root

    @property
    def path_parts(self) -> tuple[str, ...]:
        if self.parent is None:
            return ()
        return self.parent.path_parts + (self.id,)

    @field_validator("id")
    @classmethod
    def validate_delimiter(cls, v: str) -> str:
        if DOMAIN_DELIMITER in v:
            raise InvalidIdentifierException(
                f"ID '{v}' cannot contain [{DOMAIN_DELIMITER}]"
            )
        if not re.match(ID_PATTERN, v):
            raise InvalidIdentifierException(f"ID '{v}' has invalid characters")
        return v


class Source(BaseNode):
    url: str | None = None
    source_file: str | None = None
    chunks_file: str | None = None
    scraper: str | None = None
    scraper_args: dict[str, Any] = Field(default_factory=dict)

    @property
    def _collection(self) -> "DomainCollection":
        root = self.root
        if not isinstance(root, DomainCollection):
            raise OrphanSourceException(
                f"'Source '{self.id}' is not attached to a loaded DomainCollection."
            )
        return root

    @property
    def source_path(self) -> Path:
        c: DomainCollection = self._collection
        return (
            c.data_dir
            / c.sources_dir
            / Path(*self.path_parts)
            / (self.source_file or f"{self.id}.md")
        )

    @property
    def chunks_path(self) -> Path:
        c: DomainCollection = self._collection
        return (
            c.data_dir
            / c.chunks_dir
            / Path(*self.path_parts)
            / (self.chunks_file or f"{self.id}.json")
        )


class Domain(BaseNode):
    domains: list["Domain"] = Field(default_factory=list)
    sources: list["Source"] = Field(default_factory=list)

    def get_child(self, child_id: str) -> BaseNode | None:
        for child in self.domains + self.sources:
            if child.id == child_id:
                return child
        return None

    def get(self, path: str) -> BaseNode | None:
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

    def create_domain(self, path: str, **kwargs) -> "Domain":
        """
        Creates a new domain or returns an existing one based on a delimited path.
        Automatically creates any missing intermediate domains.
        """
        if not path:
            raise InvalidIdentifierException("Domain path cannot be empty.")

        parts = path.split(DOMAIN_DELIMITER)
        current = self

        for i, part in enumerate(parts):
            child = current.get_child(part)
            if child is None:
                # Apply extra arguments (like name, description) ONLY to the final target domain
                node_kwargs = kwargs if i == len(parts) - 1 else {}

                new_domain = Domain(id=part, **node_kwargs)
                new_domain._parent = current
                current.domains.append(new_domain)
                current = new_domain
            elif isinstance(child, Domain):
                # Domain exists, traverse into it
                current = child
            else:
                raise InvalidIdentifierException(
                    f"Conflict at '{part}': Cannot create domain because a Source with this ID already exists."
                )

        return current

    def create_source(self, path: str, **kwargs) -> "Source":
        """
        Creates a new Source based on a delimited path.
        Automatically creates any missing parent domains.
        """
        if not path:
            raise InvalidIdentifierException("Source path cannot be empty.")

        # Separate the parent domain path from the actual source ID
        if DOMAIN_DELIMITER in path:
            domain_path, source_id = path.rsplit(DOMAIN_DELIMITER, 1)
            parent_domain = self.create_domain(domain_path)
        else:
            parent_domain = self
            source_id = path

        # Check for conflicts to maintain ID uniqueness
        if parent_domain.get_child(source_id) is not None:
            raise InvalidIdentifierException(
                f"Cannot create source: A node with ID '{source_id}' already exists in domain '{parent_domain.id}'."
            )

        new_source = Source(id=source_id, **kwargs)
        new_source._parent = parent_domain
        parent_domain.sources.append(new_source)

        return new_source

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
        yield from self.sources

    @model_validator(mode="after")
    def _post_init_setup(self) -> "Domain":
        # Validate ID uniqueness
        child_ids = [d.id for d in self.domains] + [s.id for s in self.sources]
        if len(child_ids) != len(set(child_ids)):
            from collections import Counter

            duplicates = [id for id, count in Counter(child_ids).items() if count > 1]
            raise InvalidIdentifierException(
                f"Duplicate child IDs found in '{self.id}': {duplicates}"
            )

        # Set the child's parent
        for domain in self.domains:
            domain._parent = self
        for source in self.sources:
            source._parent = self

        return self


class DomainCollection(Domain, BaseDatorumPersistentSettings):
    sources_dir: str = Field(default="sources")
    chunks_dir: str = Field(default="chunks")

    @property
    def data_dir(self) -> Path:
        return self.filepath.parent
