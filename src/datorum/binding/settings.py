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
        """Whether this mode targets a domain rather than a single document.

        :returns: True for `domain_path` and `domain_metadata`.
        :rtype: bool
        """

        return self.value.startswith("domain")

    def is_input(self) -> bool:
        """Whether this mode allows reading (input) access.

        :returns: True for every mode except the `*-output` ones.
        :rtype: bool
        """

        return not self.value.endswith("output")

    def is_output(self) -> bool:
        """Whether this mode allows writing (output) access.

        :returns: True for every mode except the `*-input` and `*-path` ones.
        :rtype: bool
        """

        return not self.value.endswith("input") and not self.value.endswith("path")

    def is_model(self) -> bool:
        """Whether this mode resolves the target via a `DocumentReference` model.

        :returns: True for `model`, `model_input`, and `model_output`.
        :rtype: bool
        """

        return self.value.startswith("model")

    def is_text(self) -> bool:
        """Whether this mode reads/writes the target's text content directly.

        :returns: True for `text`, `text_input`, and `text_output`.
        :rtype: bool
        """

        return self.value.startswith("text")

    def is_bytes(self) -> bool:
        """Whether this mode reads/writes the target's binary content directly.

        :returns: True for `bytes`, `bytes_input`, and `bytes_output`.
        :rtype: bool
        """

        return self.value.startswith("bytes")

    def is_path(self) -> bool:
        """Whether this mode targets a filesystem path rather than content.

        :returns: True for `document_path` and `domain_path`.
        :rtype: bool
        """

        return self.value.endswith("path")

    def is_metadata(self) -> bool:
        """Whether this mode targets a document's or domain's metadata dict.

        :returns: True for `document_metadata` and `domain_metadata`.
        :rtype: bool
        """

        return self.value.endswith("metadata")

    def is_io(self) -> bool:
        """Whether this mode reads/writes content directly (model, text, or bytes).

        :returns: True unless this mode targets a path or metadata.
        :rtype: bool
        """

        return self.is_model() or self.is_text() or self.is_bytes()


class ContextBind(BaseDatorumSettings):
    """Declares how a job's context field is resolved against a `Binder`.

    Allows associating contextual information (such as a document, file, path, or
    metadata dictionary) with a specific field to be used by the Worker.

    When `local` is `True`, the information is handled in the local context after
    being copied from the shared context upon first use.
    """

    field_id: str = Field(description="Target field identifier.")
    binded_id: str = Field(description="Source document or domain ID.")
    context: str | list[str] | None = Field(
        default=None,
        description="Context ID filter.",
    )
    context_bind_type: ContextBindType = Field(
        default=ContextBindType.model,
        description="Type mode, defaults to 'ContextBindType.model'.",
    )
    local: bool = Field(
        default=False,
        description="Whether binding is local context scoped, defaults to False.",
    )


class ResourceBind(BaseDatorumSettings):
    """Binding specification linking a job field to a resource factory.

    Allows associating runtime resources (such as API key resolution) with a specific
    field to be used by the Worker.
    """

    field_id: str = Field(description="Field identifier.")
    factory_name: str = Field(description="Resource factory name.")
    selector: str | None = Field(
        default=None,
        description="Resource selector query, defaults to None.",
    )
