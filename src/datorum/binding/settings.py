from enum import Enum

from pydantic import Field

from ..core.settings import BaseDatorumSettings


class ContextBindType(str, Enum):
    """Enumeration of context binding modes and target access restrictions.
    
    This enumeration defines how the target is to be handled and the direction allowed
    by the binding.

    The target can be handled as:

    * **Model**: Resolved via the serialization/deserialization of a `DocumentReference`.
      These are items prefixed with `model`.
    * **Text**: Text file content read/written directly. These are items prefixed with
      `text`.
    * **Bytes**: Binary file content read/written directly. These are items prefixed
      with `bytes`.
    * **Path**: The path to the file referenced by the document, or to the folder
      corresponding to a domain within a context. These are items ending in `-path`.
    * **Metadata**: Metadata for a document or domain. These are items ending in
      `-metadata`. 

    The binding can allow the following directions:

    * **Input**: Used for inputting information to the Worker; treated as read-only.
      These are items ending in `-input` and `-path`. 
    * **Output**: Used for outputting information from the Worker; treated as
      write-only. Useful when the file's prior existence on disk is uncertain. These are
      items ending in `-output`. 
    * **Both**: Accessed for both reading and writing. These are items with no specific
      suffix or those ending in `-metadata`.

    """

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

    Allows associating contextual information (such as a document, file, path, or
    metadata dictionary) with a specific field to be used by the Worker.

    When `local` is `True`, the information is handled in the local context after
    being copied from the shared context upon first use.

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

    Allows associating runtime resources (such as API key resolution) with a specific
    field to be used by the Worker.

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
