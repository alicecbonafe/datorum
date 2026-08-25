from enum import Enum

from pydantic import Field

from ..core.settings import BaseDatorumSettings


class ContextBindType(str, Enum):
    """Enumeration of context binding modes and target access restrictions."""

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
        return not self.value.endswith("input") and not self.value.endswith("path")

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
    """Binding specification linking a job input/output field to a context item.

    :param field_id: Target field identifier.
    :type field_id: str
    :param binded_id: Source document or domain ID.
    :type binded_id: str
    :param context: Context ID filter
    :type context: str | list[str] | None, optional
    :param context_bind_type: Type mode, defaults to ContextBindType.model.
    :type context_bind_type: ContextBindType
    :param local: Whether binding is local context scoped, defaults to False.
    :type local: bool
    """
    field_id: str
    binded_id: str
    context: str | list[str] | None = Field(default=None)
    context_bind_type: ContextBindType = Field(default=ContextBindType.model)
    local: bool = False


class ResourceBind(BaseDatorumSettings):
    """Binding specification linking a job field to a resource factory.

    :param field_id: Field identifier.
    :type field_id: str
    :param factory_name: Resource factory name.
    :type factory_name: str
    :param selector: Resource selector query, defaults to None.
    :type selector: str | None, optional
    """

    field_id: str
    factory_name: str
    selector: str | None = None
