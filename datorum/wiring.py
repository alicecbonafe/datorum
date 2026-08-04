from enum import Enum
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Callable,
    Literal,
    Union,
)

from pydantic import BaseModel, Field

from .settings import BaseDatorumSettings


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


class BaseDocumentBind(BaseBind):

    document_id: str
    context_id: str | None = None


class DocumentBind(BaseDocumentBind):

    bind_type: Literal["document"] = "document"


class DocumentRawBind(BaseDocumentBind):

    bind_type: Literal["document-raw"] = "document-raw"


class DocumentPathBind(BaseDocumentBind):

    bind_type: Literal["document-path"] = "document-path"


class DomainPathBind(BaseBind):

    bind_type: Literal["domain"] = "domain"
    domain_id: str
    context_id: str | None = None


class ResourceBind(BaseBind):

    bind_type: Literal["resource"] = "resource"
    resource_id: str
    target_alias: str


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
    bind: Annotated[
        Union[
            DocumentBind,
            DocumentRawBind,
            DocumentPathBind,
            DomainPathBind,
            ResourceBind,
        ], Field(discriminator="bind_type")
    ] | None = None
    attribute_name: str


ResourceFactoryRegistry: dict[str, Callable] = {}


def register_resource_factory(
    resource_id: str,
    factory: Callable,
):
    ResourceFactoryRegistry[resource_id] = factory


def get_resource(
    resource_id,
    target_alias: str,
) -> Any:
    return ResourceFactoryRegistry[resource_id](target_alias)


def resource_factory(resource_id: str):
    def decorator(func):
        register_resource_factory(resource_id, func)
        return func
    return decorator