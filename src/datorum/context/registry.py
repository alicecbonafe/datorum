import inspect
import json
import shutil
from collections.abc import Callable
from pathlib import Path
import types
from typing import (
    Any,
    Callable,
    Optional,
    Self,
    Union,
    get_type_hints,
    get_origin,
    get_args,
)

import tomli_w
import tomllib
import yaml
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from .exceptions import (
    DocumentTypeError,
    DocumentModelError,
    DocumentHandlerError,
    ResourceFactoryError,
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
# | Helper
# ======================================================

def validate_factory_signature(func: Callable) -> bool:
    signature = inspect.signature(func)
    params = signature.parameters

    for param in params.values():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            return False

    if any(
        p.kind == inspect.Parameter.KEYWORD_ONLY \
            and p.default is inspect.Parameter.empty \
                for p in params.values()
    ):
        return False

    pos_params = [
        p for p in params.values()
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD
        ) and p.default is inspect.Parameter.empty
    ]

    if len(pos_params) != 1:
        return False

    param = pos_params[0]

    if param.annotation is inspect.Parameter.empty:
        return True

    hints = get_type_hints(func, include_extras=True)
    param_type = hints.get(param.name, param.annotation)

    if param_type is Any or param_type is object:
        return True

    origin = get_origin(param_type)
    if origin is Union:
        args = get_args(param_type)
    # *** unreachable? ***
    # elif hasattr(param_type, "__origin__") and param_type.__origin__ in (Union, types.UnionType):
    #     args = param_type.__args__
    else:
        args = None

    if args is None:
        return False

    expected_types = (str, type(None))
    for exp in expected_types:
        if not any(issubclass(exp, arg) for arg in args):
            return False

    return True

# ======================================================
# | Registry
# ======================================================

DocumentTypeRegistry: dict[str, DocumentType] = {}
DocumentModelRegistry: dict[str, DocumentModel] = {}
DocumentHandlerRegistry: dict[tuple[str, str], DocumentHandler] = {}
ResourceFactoryRegistry: dict[str, Callable] = {}


def register_doc_type(id: str, extentions: list[str], force: bool = False) -> DocumentType:
    if id in DocumentTypeRegistry and not force:
        raise DocumentTypeError(f"Doc type '{id}' is already registered")
    doc_type = DocumentType(id=id, extentions=extentions)
    DocumentTypeRegistry[id] = doc_type
    return doc_type

def get_doc_type(id: str) -> Optional[DocumentType]:
    if id not in DocumentTypeRegistry:
        raise DocumentTypeError(f"Doc type '{id}' not found in registry")
    return DocumentTypeRegistry[id]


def register_doc_model(id: str, clazz: type, default_doc_type: str | None = None, force: bool = False) -> DocumentModel:
    if id in DocumentModelRegistry and not force:
        raise DocumentModelError(f"Doc model '{id}' is already registered")
    doc_model = DocumentModel(id=id, clazz=clazz)
    if default_doc_type:
        doc_model.default_doc_type = default_doc_type
    DocumentModelRegistry[id] = doc_model
    return doc_model

def get_doc_model(id: str) -> Optional[DocumentType]:
    if id not in DocumentModelRegistry:
        raise DocumentModelError(f"Doc model '{id}' not found in registry")
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

def get_doc_handler(doc_type: str, doc_model: str, create: bool = False) -> Optional[DocumentType]:
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
    if doc_type is None and doc_model is None:
        return list(DocumentHandlerRegistry.values())
    if doc_type is None:
        return [val for key, val in DocumentHandlerRegistry.items() if key[1] == doc_model]
    if doc_model is None:
        return [val for key, val in DocumentHandlerRegistry.items() if key[0] == doc_type]
    handler_id = (doc_type, doc_model)
    return [DocumentHandlerRegistry[handler_id]] if handler_id in DocumentHandlerRegistry else []


def register_resource_factory(name: str, factory: Callable, force: bool = False) -> Callable:
    if name in ResourceFactoryRegistry and not force:
        raise ResourceFactoryError(
            f"Resource factory '{name}' is already registered, use 'force=True' to overwrite")
    if not validate_factory_signature(factory):
        raise ResourceFactoryError(
            f"Resource factory '{name}' has not a compatible signature")
    ResourceFactoryRegistry[name] = factory
    return factory

def get_resource_factory(factory_name: str) -> Callable:
    if factory_name not in ResourceFactoryRegistry:
        raise ResourceFactoryError(f"Resource factory '{factory_name}' not found")
    return ResourceFactoryRegistry[factory_name]


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
    def decorator(func):
        get_doc_handler(doc_type=doc_type, doc_model=doc_model, create=True).serializer = func
        return func

    return decorator


def deserializer(doc_type: str, doc_model: str):
    def decorator(func):
        get_doc_handler(
            doc_type=doc_type, doc_model=doc_model,
            create=True
        ).deserializer = func
        return func

    return decorator


def resource(name: str | None = None, force: bool = False):
    def decorator(func):
        factory_name = name or func.__name__
        return register_resource_factory(
            name=factory_name,
            factory=func,
            force=force,
        )
    return decorator


# ======================================================
# | Defaults
# ======================================================

from .defaults.simple import (
    simple_text_writer,
    simple_text_reader,
    simple_json_writer,
    simple_json_reader,
    simple_yaml_writer,
    simple_yaml_reader,
    simple_toml_writer,
    simple_toml_reader,
)
from .defaults.markdown import (
    MarkdownDocument,
    markdown_writer,
    simple_toml_reader,
)
from .defaults.chat import (
    ChatHistory,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ToolMessage,
    FunctionMessage,
    ChatMessage,
    ToolCall,
    ToolFunction,
    FunctionCall,
    ImagePart,
    TextPart,
    ImageUrl,
)