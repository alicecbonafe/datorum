from enum import Enum

from pydantic import Field

from ..core.settings import BaseDatorumSettings


class ContextBindType(str, Enum):
    model = "model"
    model_input = "model-input"
    model_output = "model-output"
    text = "text"
    text_input = "text-input"
    text_output = "text-output"
    bytes = "bytes"
    bytes_input = "bytes-input"
    bytes_output = "bytes-output"
    document_path = "document-path"
    document_metadata = "document-metadata"
    domain_path = "domain-path"
    domain_metadata = "domain-metadata"

    def is_domain(self) -> bool:
        return self.value.startswith("domain")

    def is_input(self) -> bool:
        return not self.value.endswith("output")

    def is_output(self) -> bool:
        return not self.value.endswith("input") \
            and not self.value.endswith("path")

    def is_model(self) -> bool:
        return self.value.startswith("model")

    def is_text(self) -> bool:
        return self.value.startswith("text")

    def is_bytes(self) -> bool:
        return self.value.startswith("bytes")

    def is_path(self) -> bool:
        return self.value.endswith("path")

    def is_metadata(self) -> bool:
        return self.value.endswith("metadata")

    def is_io(self) -> bool:
        return self.is_model() or self.is_text() or self.is_bytes()


class ContextBind(BaseDatorumSettings):
    field_id: str
    binded_id: str
    context: str | list[str] | None = Field(default=None)
    context_bind_type: ContextBindType = Field(default=ContextBindType.model)


class ResourceBind(BaseDatorumSettings):
    field_id: str
    factory_name: str
    selector: str | None = None
