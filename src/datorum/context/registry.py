import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import tomli_w
import yaml
from pydantic import BaseModel, Field, PrivateAttr

from .exceptions import (
    DocumentHandlerError,
    DocumentModelError,
    DocumentTypeError,
)

# ======================================================
# | Classes
# ======================================================


class DocumentType(BaseModel):
    """Represents the document content type, as writen in file, such as json or markdown.

    :param id: MIME-style content type identifier.
    :type id: str
    :param extensions: List of extensions associated with this document type.
    :type extensions: list[str]
    """

    id: str = Field(description="MIME-style content type identifier.")
    extensions: list[str] = Field(
        default_factory=list,
        description="List of extensions associated with this document type.",
    )


class DocumentModel(BaseModel):
    """Maps a Python class to a document model identifier.
    
    :param id: Document model identifier.
    :type id: str
    :param clazz: Python class bound to this model.
    :type clazz: type
    :param default_doc_type: Default content type for serialization.
    :type default_doc_type: str
    """

    id: str = Field(description="Document model identifier.")
    clazz: type = Field(description="Python class bound to this model.")
    default_doc_type: str = Field(
        default="application/json",
        description="Default content type for serialization.",
    )


class DocumentHandler(BaseModel):
    """Holds serializer and deserializer callables for a content type and model pair.

    :param doc_type: Document type identifier.
    :type doc_type: str
    :param doc_model: Document model identifier.
    :type doc_model: str
    """

    doc_type: str = Field(description="Document type identifier.")
    doc_model: str = Field(description="Document model identifier.")

    _serializer: Callable | None = PrivateAttr(default=None)
    _deserializer: Callable | None = PrivateAttr(default=None)

    @property
    def id(self) -> tuple[str, str]:
        return (self.doc_type, self.doc_model)

    @property
    def serializer(self) -> Callable | None:
        return self._serializer

    @serializer.setter
    def serializer(self, value: Callable):
        self._serializer = value

    @property
    def deserializer(self) -> Callable | None:
        return self._deserializer

    @deserializer.setter
    def deserializer(self, value: Callable | None):
        self._deserializer = value


# ======================================================
# | Registry
# ======================================================

DocumentTypeRegistry: dict[str, DocumentType] = {}
DocumentModelRegistry: dict[str, DocumentModel] = {}
DocumentHandlerRegistry: dict[tuple[str, str], DocumentHandler] = {}


def register_doc_type(
    id: str, extensions: list[str], force: bool = False
) -> DocumentType:
    """Register a new document content type.

    :param id: MIME-style content type string.
    :type id: str
    :param extensions: File extension aliases.
    :type extensions: list[str]
    :param force: Whether to overwrite existing registration, defaults to False.
    :type force: bool, optional
    :returns: Registered `DocumentType` instance.
    :rtype: DocumentType
    :raises DocumentTypeError: If already registered and `force` is False.
    """
    if id in DocumentTypeRegistry and not force:
        raise DocumentTypeError(f"Doc type '{id}' is already registered")
    doc_type = DocumentType(id=id, extensions=extensions)
    DocumentTypeRegistry[id] = doc_type
    return doc_type


def get_doc_type(id: str) -> DocumentType:
    """Retrieve a registered document type by identifier.

    :param id: Content type identifier.
    :type id: str
    :returns: Found `DocumentType` instance.
    :rtype: DocumentType
    :raises DocumentTypeError: If the type is not registered.
    """
    if id not in DocumentTypeRegistry:
        raise DocumentTypeError(f"Doc type '{id}' not found in registry")
    return DocumentTypeRegistry[id]


def register_doc_model(
    id: str, clazz: type, default_doc_type: str | None = None, force: bool = False
) -> DocumentModel:
    """Register a class as a document model.

    :param id: Document model identifier
    :type id: str
    :param clazz: Target Python class.
    :type clazz: type
    :param default_doc_type: Default content type, defaults to 'application/json'.
    :type default_doc_type: str | None, optional
    :param force: Overwrite existing registration, defaults to False.
    :type force: bool, optional
    :returns: Registered `DocumentModel`.
    :rtype: DocumentModel
    :raises DocumentModelError: If already registered and `force` is False.
    """
    if id in DocumentModelRegistry and not force:
        raise DocumentModelError(f"Doc model '{id}' is already registered")
    doc_model = DocumentModel(id=id, clazz=clazz)
    if default_doc_type:
        doc_model.default_doc_type = default_doc_type
    DocumentModelRegistry[id] = doc_model
    return doc_model


def get_doc_model(id: str) -> DocumentModel:
    """Retrieve a registered document model by identifier.

    :param id: Model identifier
    :type id: str
    :returns: Found `DocumentModel` instance
    :rtype: DocumentModel
    :raises DocumentModelError: If the model is not found.
    """
    if id not in DocumentModelRegistry:
        raise DocumentModelError(f"Doc model '{id}' not found in registry")
    return DocumentModelRegistry[id]


def register_pydantic_based_handler(
    model_type: type[BaseModel],
    model_id: str | None = None,
    doc_type: str | None = None,  # None == all (json, yaml, toml)
    doc_model: str | None = None,
):
    """Register serialization handlers for a Pydantic model class.

    :param model_type: Pydantic model subclass.
    :type model_type: type
    :param model_id: Optional model identifier override.
    :type model_id: str | None, optional
    :param doc_type: Target document content type.
    :type doc_type: str | None, optional
    :param doc_model: Model name alias.
    :type doc_model: str | None, optional
    :raises DocumentHandlerError: If prerequisite dict handler missing.
    """
    model_id = model_id or doc_model or model_type.__name__

    DocumentModelRegistry[model_id] = DocumentModel(
        id=model_id,
        clazz=model_type,
        default_doc_type=doc_type or "application/json",
    )

    doc_types = (
        [doc_type]
        if doc_type is not None
        else [
            "application/json",
            "application/yaml",
            "application/toml",
        ]
    )

    for dt in doc_types:
        dict_handler = DocumentHandlerRegistry.get((dt, "dict"))
        if (
            dict_handler is None
            or dict_handler.serializer is None
            or dict_handler.deserializer is None
        ):
            raise DocumentHandlerError(
                f"No dict serializer/deserializer registered for doc_type '{dt}' "
                f"(register a dict handler before wrapping it for a model)"
            )

        def _make_serializer(dict_writer):
            def _serialize(data: BaseModel, file_path: Path):
                dict_writer(data.model_dump(mode="json"), file_path)

            return _serialize

        def _make_deserializer(dict_reader, model_cls):
            def _deserialize(file_path: Path) -> BaseModel:
                return model_cls.model_validate(dict_reader(file_path))

            return _deserialize

        handler = get_doc_handler(doc_type=dt, doc_model=model_id, create=True)
        handler.serializer = _make_serializer(dict_handler.serializer)
        handler.deserializer = _make_deserializer(dict_handler.deserializer, model_type)


def get_doc_handler(
    doc_type: str, doc_model: str, create: bool = False
) -> DocumentHandler:
    """Retrieve or create a document handler pair.

    :param doc_type: Target content type.
    :type doc_type: str
    :param doc_model: Target model identifier.
    :type doc_model: str
    :param create: Automatically instantiate if missing, defaults to False.
    :type create: bool, optional
    :returns: Document handler instance.
    :rtype: DocumentHandler
    :raises DocumentHandlerError: If missing and `create` is False.
    """
    id = (doc_type, doc_model)
    if id not in DocumentHandlerRegistry:
        if create:
            DocumentHandlerRegistry[id] = DocumentHandler(
                doc_type=doc_type,
                doc_model=doc_model,
            )
        else:
            raise DocumentHandlerError(f"Doc model '{id}' not found in registry")
    return DocumentHandlerRegistry[id]


def find_handlers(
    doc_type: str | None = None, doc_model: str | None = None
) -> list[DocumentHandler]:
    """Find registered document handlers matching optional filter criteria.

    :param doc_type: Filter by content type.
    :type doc_type: str | None, optional
    :param doc_model: Filter by document model.
    :type doc_model: str | None, optional
    :returns: Matching document handler list.
    :rtype: list[DocumentHandler]
    """
    if doc_type is None and doc_model is None:
        return list(DocumentHandlerRegistry.values())
    if doc_type is None:
        return [
            val for key, val in DocumentHandlerRegistry.items() if key[1] == doc_model
        ]
    if doc_model is None:
        return [
            val for key, val in DocumentHandlerRegistry.items() if key[0] == doc_type
        ]
    handler_id = (doc_type, doc_model)
    return (
        [DocumentHandlerRegistry[handler_id]]
        if handler_id in DocumentHandlerRegistry
        else []
    )


# ======================================================
# | Decorators
# ======================================================


def doc_model(id: str, doc_type: str | None = None, force: bool = False):
    """Decorator to register a class as a document model.

    :param id: Document model identifier.
    :type id: str
    :param doc_type: Default content type.
    :type doc_type: str | None, optional
    :param force: Overwrite existing registration, defaults to False.
    :type force: bool, optional
    """

    def decorator(cls):
        if issubclass(cls, BaseModel):
            register_pydantic_based_handler(
                model_type=cls,
                model_id=id,
                doc_type=doc_type,
            )
        elif id in DocumentModelRegistry and not force:
            raise DocumentModelError(f"Doc model '{id}' is already registrered")
        else:
            DocumentModelRegistry[id] = DocumentModel(
                id=id,
                clazz=cls,
                default_doc_type=doc_type or "application/json",
            )
        return cls

    return decorator


def serializer(doc_type: str, doc_model: str):
    """Decorator to register a document serializer function.

    :param doc_type: Content type identifier.
    :type doc_type: str
    :param doc_model: Document model identifier.
    :type doc_model: str
    """

    def decorator(func):
        get_doc_handler(
            doc_type=doc_type, doc_model=doc_model, create=True
        ).serializer = func
        return func

    return decorator


def deserializer(doc_type: str, doc_model: str):
    """Decorator to register a document deserializer function.

    :param doc_type: Content type identifier.
    :type doc_type: str
    :param doc_model: Document model identifier.
    :type doc_model: str
    """

    def decorator(func):
        get_doc_handler(
            doc_type=doc_type, doc_model=doc_model, create=True
        ).deserializer = func
        return func

    return decorator


# ======================================================
# | Basic handlers
# ======================================================


register_doc_type("text/plain", ["txt"])
register_doc_type("application/json", ["json"])
register_doc_type("application/yaml", ["yml", "yaml"])
register_doc_type("application/toml", ["toml"])

DocumentModelRegistry["text"] = DocumentModel(id="text", clazz=str)
DocumentModelRegistry["dict"] = DocumentModel(id="dict", clazz=dict)


@serializer(doc_type="text/plain", doc_model="text")
def simple_text_writer(data: str, file_path: Path):
    file_path.write_text(data, encoding="utf-8")


@deserializer(doc_type="text/plain", doc_model="text")
def simple_text_reader(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


@serializer(doc_type="application/json", doc_model="dict")
def simple_json_writer(data: dict, file_path: Path):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    file_path.write_text(text)


@deserializer(doc_type="application/json", doc_model="dict")
def simple_json_reader(file_path: Path) -> dict:
    text = file_path.read_text(encoding="utf-8")
    return json.loads(text)


@serializer(doc_type="application/yaml", doc_model="dict")
def simple_yaml_writer(data: dict, file_path: Path):
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    file_path.write_text(text)


@deserializer(doc_type="application/yaml", doc_model="dict")
def simple_yaml_reader(file_path: Path) -> dict:
    text = file_path.read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


@serializer(doc_type="application/toml", doc_model="dict")
def simple_toml_writer(data: dict, file_path: Path):
    text = tomli_w.dumps(data)
    file_path.write_text(text)


@deserializer(doc_type="application/toml", doc_model="dict")
def simple_toml_reader(file_path: Path) -> dict:
    text = file_path.read_text(encoding="utf-8")
    return tomllib.loads(text)
