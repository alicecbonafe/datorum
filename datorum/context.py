from pathlib import Path
from typing import Any, Optional, Callable

from pydantic import BaseModel, Field, PrivateAttr, model_validator

import json
import shutil
import tomllib
import tomli_w
import yaml

from .settings_base import BaseDatorumSettings
from .exceptions import (
    NoFilePathException,
    DocumentNotFoundException,
    DocumentNotLoadedException,
    UnknownDataModelException,
    DocumentFormatException,
)


# ======================================================
# | Classes
# ======================================================

class DocumentType(BaseModel):

    id: str
    extentions: list[str] = Field(default_factory=list)

class DocumentModel(BaseModel):

    id: str
    clazz: type
    default_doc_type: str = Field(default="application/json")

class DocumentHandler(BaseModel):

    doc_type: str
    doc_model: str

    _serializer: Optional[Callable] = PrivateAttr(default=None)
    _deserializer: Optional[callable] = PrivateAttr(default=None)

    @property
    def id(self) -> tuple[str, str]:
        return (self.doc_type, self.doc_model)

    @property
    def serializer(self) -> Optional[Callable]:
        return self._serializer

    @serializer.setter
    def serializer(self, value: Callable):
        self._serializer = value

    @property
    def deserializer(self) -> Optional[Callable]:
        return self._deserializer

    @deserializer.setter
    def deserializer(self, value: Optional[Callable]):
        self._deserializer = value


# ======================================================
# | Registry
# ======================================================

DOC_TYPES: dict[str, DocumentType] = {}
DOC_MODELS: dict[str, DocumentModel] = {}
DOC_HANDLERS: dict[str, DocumentHandler] = {}

def register_doc_type(id: str, extentions: list[str]) -> DocumentType:
    doc_type = DocumentType(id=id, extentions=extentions)
    DOC_TYPES[id] = doc_type
    return doc_type

def register_pydantic_based_handler(
    model_type: type[BaseModel],
    doc_type: str | None = None, # None == all (json, yaml, toml)
    doc_model: str | None = None,
):
    model_id = doc_model or model_type.__name__

    DOC_MODELS[model_id] = DocumentModel(
        id=model_id,
        clazz=model_type,
        default_doc_type=doc_type or "application/json",
    )

    doc_types = [doc_type] if doc_type is not None else [
        "application/json", "application/yaml", "application/toml",
    ]

    for dt in doc_types:
        dict_handler = DOC_HANDLERS.get((dt, "dict"))
        if dict_handler is None or dict_handler.serializer is None or dict_handler.deserializer is None:
            raise DocumentFormatException(
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

        handler = get_or_create_handler(doc_type=dt, doc_model=model_id)
        handler.serializer = _make_serializer(dict_handler.serializer)
        handler.deserializer = _make_deserializer(dict_handler.deserializer, model_type)

def get_or_create_handler(doc_type: str, doc_model: str) -> DocumentHandler:
    id = (doc_type, doc_model)
    if id not in DOC_HANDLERS:
        DOC_HANDLERS[id] = DocumentHandler(
            doc_type=doc_type,
            doc_model=doc_model,
        )
    return DOC_HANDLERS[id]

def find_handlers(doc_type: str | None = None, doc_model: str | None = None) -> list[DocumentHandler]:
    if doc_type is None and doc_model is None:
        return list(DOC_HANDLERS.values())
    if doc_type is None:
        return [val for key, val in DOC_HANDLERS.items() if key[1] == doc_model]
    if doc_model is None:
        return [val for key, val in DOC_HANDLERS.items() if key[0] == doc_type]
    handler_id = (doc_type, doc_model)
    return [DOC_HANDLERS[handler_id]] if handler_id in DOC_HANDLERS else []


# ======================================================
# | Decorators
# ======================================================

def doc_model(id: str, doc_type: str | None = None):
    def decorator(cls):
        if issubclass(cls, BaseModel):
            register_pydantic_based_handler(
                model_type=cls,
                doc_type=doc_type,
            )
        else:
            DOC_MODELS[id] = DocumentModel(
                id=id, clazz=cls,
                default_doc_type=doc_type or "application/json",
            )
        return cls
    return decorator

def serializer(doc_type: str, doc_model: str):
    def decorator(func):
        get_or_create_handler(
            doc_type=doc_type, doc_model=doc_model).serializer = func
        return func
    return decorator

def deserializer(doc_type: str, doc_model: str):
    def decorator(func):
        get_or_create_handler(
            doc_type=doc_type, doc_model=doc_model).deserializer = func
        return func
    return decorator


# ======================================================
# | Defaults
# ======================================================

register_doc_type("text/plain", ["txt"])
register_doc_type("text/markdown", ["md", "markdown", "markdn", "mdown"])
register_doc_type("application/json", ["json"])
register_doc_type("application/yaml", ["yml", "yaml"])
register_doc_type("application/toml", ["toml"])

DOC_MODELS["text"] = DocumentModel(id="text", clazz=str)
DOC_MODELS["dict"] = DocumentModel(id="dict", clazz=dict)

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



# ======================================================
# | Settings
# ======================================================


class DocumentReference(BaseDatorumSettings):

    id: str
    doc_type: str = "text/plain"
    doc_model: str = "text"

    metadata: dict[str, Any] = Field(default_factory=dict)

    _context: Optional["DocumentContext"] = PrivateAttr(default=None)

    @property
    def context(self) -> "DocumentContext":
        if self._context is None:
            raise ValueError(f"Document '{self.id}' is out of context")
        return self._context

    @property
    def registry_doc_type(self) -> DocumentType:
        try:
            return DOC_TYPES[self.doc_type]
        except KeyError:
            raise DocumentFormatException(f"Unknown doc_type '{self.doc_type}'") from None

    @property
    def registry_doc_model(self) -> DocumentModel:
        try:
            return DOC_MODELS[self.doc_model]
        except KeyError:
            raise UnknownDataModelException(f"Unknown doc_model '{self.doc_model}'") from None

    @property
    def registry_doc_handler(self) -> DocumentHandler:
        handler = DOC_HANDLERS.get((self.doc_type, self.doc_model))
        if handler is None:
            raise DocumentFormatException(
                f"No handler registered for doc_type='{self.doc_type}', doc_model='{self.doc_model}'"
            )
        return handler

    @property
    def base_path(self) -> Path:
        return self.context.base_path

    @property
    def name(self) -> str:
        return self.id.split(".")[-1]

    @property
    def domain_list(self) -> list[str]:
        return self.id.split(".")[:-1]

    @property
    def domain(self) -> str:
        return ".".join(self.domain_list)

    @property
    def doc_path(self) -> Path:
        name = self.name
        domain_list = self.domain_list

        doc_path = self.base_path
        for domain in domain_list:
            doc_path = doc_path / domain
        doc_path = doc_path / name

        extentions = self.registry_doc_type.extentions
        has_ext = any(name.endswith(f".{ext}") for ext in extentions)
        if not has_ext and extentions:
            doc_path = doc_path.with_suffix(f".{extentions[0]}")

        return doc_path

    def load(self) -> Any:
        doc_path = self.doc_path
        if not doc_path.exists():
            raise DocumentNotFoundException(f"Document '{self.id}' not found at '{doc_path}'")

        handler = self.registry_doc_handler
        if handler.deserializer is None:
            raise DocumentFormatException(
                f"No deserializer registered for doc_type='{self.doc_type}', doc_model='{self.doc_model}'"
            )
        return handler.deserializer(doc_path)

    def save(self, data: Any) -> Path:
        expected_type = self.registry_doc_model.clazz
        if not isinstance(data, expected_type):
            raise TypeError(
                f"Expected instance of {expected_type.__name__} for doc_model "
                f"'{self.doc_model}', got {type(data).__name__}"
            )

        handler = self.registry_doc_handler
        if handler.serializer is None:
            raise DocumentFormatException(
                f"No serializer registered for doc_type='{self.doc_type}', doc_model='{self.doc_model}'"
            )

        doc_path = self.doc_path
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        handler.serializer(data, doc_path)
        return doc_path

    def copy_to(self, target: "Document") -> "Document":
        if self.doc_model != target.doc_model:
            raise DocumentFormatException(f"Cannot copy a '{self.doc_model}' to '{target.doc_model}'")

        src_path = self.doc_path
        if not src_path.exists():
            raise DocumentNotFoundException(f"Document '{self.id}' not found at '{src_path}'")

        dst_path = target.doc_path

        if dst_path != src_path:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if self.doc_type == target.doc_type:
                shutil.copy2(src_path, dst_path)
            else:
                target.save(self.load())

        return target


class DocumentContext(BaseDatorumSettings):

    id: str
    documents: dict[str, DocumentReference] = Field(default_factory=dict)
    domain_metadata: dict[str, Any] = Field(default_factory=dict)

    _base_path: Path | None = PrivateAttr(default=None)

    @property
    def base_path(self) -> Path:
        if self._base_path is None:
            return self.settings_path.parent
        return self._base_path

    @base_path.setter
    def base_path(self, value: Path):
        self._base_path = value

    def get_document(self, id: str) -> DocumentReference | None:
        return self.documents.get(id)

    def create_document(self, id: str, doc_type: str = "text/plain", doc_model: str = "text"):
        document = DocumentReference(
            id=id,
            doc_type=doc_type,
            doc_model=doc_model,
        )
        self.documents[id] = document
        document._context = self
        return document

    def drop_document(self, id: str, remove_file: bool = False):
        if remove_file:
            doc_path = self.documents[id].doc_path
            if doc_path.exists():
                doc_path.unlink()
        del self.documents[id]

    @model_validator(mode="after")
    def _set_context(self) -> "DocumentContext":
        for document in self.documents.values():
            document._context = self
        return self
