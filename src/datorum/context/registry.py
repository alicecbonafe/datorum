import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional, Self

import tomli_w
import tomllib
import yaml
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from ..exceptions import (
    DocumentFormatException,
    DocumentNotFoundException,
    UnknownDataModelException,
    InvalidIdentifierException,
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


def register_doc_type(id: str, extentions: list[str], force: bool = False) -> DocumentType:
    if id in DocumentTypeRegistry and not force:
        raise DocumentFormatException(f"Doc type '{id}' is already registered")
    doc_type = DocumentType(id=id, extentions=extentions)
    DocumentTypeRegistry[id] = doc_type
    return doc_type

def get_doc_type(id: str) -> Optional[DocumentType]:
    if id not in DocumentTypeRegistry:
        raise InvalidIdentifierException(f"Doc type '{id}' not found in registry")
    return DocumentTypeRegistry[id]


def register_doc_model(id: str, clazz: type, default_doc_type: str | None = None, force: bool = False) -> DocumentModel:
    if id in DocumentModelRegistry and not force:
        raise DocumentFormatException(f"Doc model '{id}' is already registered")
    doc_model = DocumentModel(id=id, clazz=clazz)
    if default_doc_type:
        doc_model.default_doc_type = default_doc_type
    DocumentModelRegistry[id] = doc_model
    return doc_model

def get_doc_model(id: str) -> Optional[DocumentType]:
    if id not in DocumentModelRegistry:
        raise InvalidIdentifierException(f"Doc model '{id}' not found in registry")
    return DocumentModelRegistry[id]


def register_pydantic_based_handler(
    model_type: type[BaseModel],
    model_id: str | None = None,
    doc_type: str | None = None,  # None == all (json, yaml, toml)
    doc_model: str | None = None,
):
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
    if id not in DocumentHandlerRegistry:
        DocumentHandlerRegistry[id] = DocumentHandler(
            doc_type=doc_type,
            doc_model=doc_model,
        )
    return DocumentHandlerRegistry[id]

def find_handlers(
    doc_type: str | None = None, doc_model: str | None = None
) -> list[DocumentHandler]:
    if doc_type is None and doc_model is None:
        return list(DocumentHandlerRegistry.values())
    if doc_type is None:
        return [val for key, val in DocumentHandlerRegistry.items() if key[1] == doc_model]
    if doc_model is None:
        return [val for key, val in DocumentHandlerRegistry.items() if key[0] == doc_type]
    handler_id = (doc_type, doc_model)
    return [DocumentHandlerRegistry[handler_id]] if handler_id in DocumentHandlerRegistry else []


# ======================================================
# | Decorators
# ======================================================


def doc_model(id: str, doc_type: str | None = None, force: bool = False):
    def decorator(cls):
        if issubclass(cls, BaseModel):
            register_pydantic_based_handler(
                model_type=cls,
                model_id=id,
                doc_type=doc_type,
            )
        elif id in DocumentModelRegistry and not force:
            raise DocumentFormatException(f"Doc model '{id}' is already registrered")
        else:
            DocumentModelRegistry[id] = DocumentModel(
                id=id,
                clazz=cls,
                default_doc_type=doc_type or "application/json",
            )
        return cls

    return decorator


def serializer(doc_type: str, doc_model: str):
    def decorator(func):
        get_or_create_handler(doc_type=doc_type, doc_model=doc_model).serializer = func
        return func

    return decorator


def deserializer(doc_type: str, doc_model: str):
    def decorator(func):
        get_or_create_handler(
            doc_type=doc_type, doc_model=doc_model
        ).deserializer = func
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


# ======================================================
# | Markdown Model
# ======================================================


@doc_model(id="markdown", doc_type="text/markdown")
class MarkdownDocument:

    FRONTMATTER_YAML = "yaml"
    FRONTMATTER_JSON = "json"
    FRONTMATTER_TOML = "toml"

    DELIMITER_YAML = "---\n"
    DELIMITER_JSON = ";;;\n"
    DELIMITER_TOML = "+++\n"

    def __init__(self, content: str, frontmatter: dict | None = None, frontmatter_format: str | None = None):
        self.content = content
        self.frontmatter = frontmatter
        self.frontmatter_format = frontmatter_format or self.FRONTMATTER_YAML

    def dumps(self) -> str:
        raw = self.content
        if self.frontmatter_format == self.FRONTMATTER_YAML:
            frontmatter_raw = yaml.safe_dump(self.frontmatter, sort_keys=False, allow_unicode=True)
            raw = f"{self.DELIMITER_YAML}{frontmatter_raw}\n{self.DELIMITER_YAML}\n{raw}"
        elif self.frontmatter_format == self.FRONTMATTER_JSON:
            frontmatter_raw = json.dumps(self.frontmatter, indent=2, ensure_ascii=False)
            raw = f"{self.DELIMITER_JSON}{frontmatter_raw}\n{self.DELIMITER_JSON}\n{raw}"
        elif self.frontmatter_format == self.FRONTMATTER_TOML:
            frontmatter_raw = tomli_w.dumps(self.frontmatter)
            raw = f"{self.DELIMITER_TOML}{frontmatter_raw}\n{self.DELIMITER_TOML}\n{raw}"
        return raw

    def dump(self, file_path: Path):
        file_path.write_text(self.dumps(), encoding="utf-8")

    @classmethod
    def loads(cls, raw: str) -> Self:
        content: str = raw
        frontmatter: dict | None = None
        frontmatter_format: str | None = None

        if raw.startswith(cls.DELIMITER_YAML):
            closure = raw.find(cls.DELIMITER_YAML, len(cls.DELIMITER_YAML))
            if closure > 0:
                frontmatter_format = cls.FRONTMATTER_YAML
                frontmatter_raw = raw[len(cls.DELIMITER_YAML):closure]
                frontmatter = yaml.safe_load(frontmatter_raw) or {}
                content = raw[closure+len(cls.DELIMITER_YAML):]
        elif raw.startswith(cls.DELIMITER_JSON):
            closure = raw.find(cls.DELIMITER_JSON, len(cls.DELIMITER_JSON))
            if closure > 0:
                frontmatter_format = cls.FRONTMATTER_JSON
                frontmatter_raw = raw[len(cls.DELIMITER_JSON):closure]
                frontmatter = json.loads(frontmatter_raw)
                content = raw[closure+len(cls.DELIMITER_JSON):]
        elif raw.startswith(cls.DELIMITER_TOML):
            closure = raw.find(cls.DELIMITER_TOML, len(cls.DELIMITER_TOML))
            if closure > 0:
                frontmatter_format = cls.FRONTMATTER_TOML
                frontmatter_raw = raw[len(cls.DELIMITER_TOML):closure]
                frontmatter = tomllib.loads(frontmatter_raw)
                content = raw[closure+len(cls.DELIMITER_TOML):]

        return cls(
            content=content.strip(),
            frontmatter=frontmatter,
            frontmatter_format=frontmatter_format,
        )

    @classmethod
    def load(cls, file_path: Path) -> Self:
        return cls.loads(file_path.read_text(encoding="utf-8"))


@serializer(doc_type="text/markdown", doc_model="markdown")
def markdown_writer(data: MarkdownDocument, file_path: Path):
    data.dump(file_path=file_path)


@deserializer(doc_type="text/markdown", doc_model="markdown")
def simple_toml_reader(file_path: Path) -> MarkdownDocument:
    return MarkdownDocument.load(file_path=file_path)