from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Callable,
    Literal,
)

from pydantic import Field

from .settings import BaseDatorumSettings
from .context import DocumentReference


class TargetConnector(str, Enum):
    TOOLBOX_SETTINGS = "toolbox-settings"
    TOOLBOX_ATTRIBUTE = "toolbox-attribute"
    TOOL_PARAMETER = "tool-parameter"
    TOOL_RESULT = "tool-result"

    AGENT_SYSTEM_INSTRUCTIONS = "agent-system-instructions"
    AGENT_USER_PROMPT = "agent-user-prompt"
    AGENT_INFERENCE_RESULT = "agent-inference-result"

    HUMAN_INTERFACE = "human-interface"
    HUMAN_ADDITIONAL = "human-additional"


class DocumentConnector(str, Enum):
    DATA = "data"
    PATH = "path"
    RAW = "raw"


class BaseBind(BaseDatorumSettings):
    bind_type: str

    def resolve(
        self,
        documents: dict[str, DocumentReference],
        domains: dict[str, Path],
        resources: dict[str, Any],
    ) -> Any: ...


class BaseDocumentBind(BaseBind):
    document_id: str


class DocumentBind(BaseDocumentBind):
    bind_type: Literal["doc"] = "doc"

    def resolve(
        self,
        documents: dict[str, DocumentReference],
        domains: dict[str, Path],
        resources: dict[str, Any],
    ) -> Any:
        return documents[self.document_id].load()


class DocumentRawBind(BaseDocumentBind):
    bind_type: Literal["doc-raw"] = "doc-raw"

    def resolve(
        self,
        documents: dict[str, DocumentReference],
        domains: dict[str, Path],
        resources: dict[str, Callable],
    ) -> Any:
        if self.document_id not in documents:
            return None
        return documents[self.document_id].doc_path.read_text(encoding="utf-8")


class DocumentPathBind(BaseDocumentBind):
    bind_type: Literal["doc-path"] = "doc-path"

    def resolve(
        self,
        documents: dict[str, DocumentReference],
        domains: dict[str, Path],
        resources: dict[str, Callable],
    ) -> Any:
        if self.document_id not in documents:
            return None
        return documents[self.document_id].doc_path


class DomainPathBind(BaseBind):
    bind_type: Literal["domain"] = "domain"
    domain_id: str

    def resolve(
        self,
        documents: dict[str, DocumentReference],
        domains: dict[str, Path],
        resources: dict[str, Callable],
    ) -> Any:
        if self.domain_id not in domains:
            return None
        return domains[self.domain_id]


class ResourceBind(BaseBind):
    bind_type: Literal["resource"] = "resource"
    resource_id: str
    target_alias: str

    def resolve(
        self,
        documents: dict[str, DocumentReference],
        domains: dict[str, Path],
        resources: dict[str, Callable],
    ) -> Any:
        if self.resource_id not in resources  :
            return None
        return resources[self.resource_id](self.target_alias)


class BasePort(BaseDatorumSettings):
    port_type: str
    bind: BaseBind | None


class InputPort(BasePort):
    port_type: Literal["input"] = "input"
    bind: DocumentBind | None = None


class OutputPort(BasePort):
    port_type: Literal["output"] = "output"
    bind: DocumentBind | None = None


class LivePort(BasePort):
    port_type: Literal["live"] = "live"
    bind: DocumentBind | None = None


class ResourcePort(BasePort):
    port_type: Literal["resource"] = "resource"
    bind: ResourceBind | None = None
    attribute_name: str | None = None


class CustomPort(BasePort):
    port_type: Literal["custom"] = "custom"
    bind: (
        Annotated[
            DocumentBind
            | DocumentRawBind
            | DocumentPathBind
            | DomainPathBind
            | ResourceBind,
            Field(discriminator="bind_type"),
        ]
        | None
    ) = None
    attribute_name: str  # TODO deprecate?
