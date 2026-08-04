from enum import Enum
import inspect
from logging import Logger
from typing import (
    Any,
    Callable,
    Literal,
    Optional,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel, Field, PrivateAttr, create_model, model_validator

from .settings_base import BaseDatorumSettings, BaseDatorumPersistentSettings
from .wiring import (
    InputPort,
    OutputPort,
    ResourcePort,
    CustomPort,
)
from .exceptions import InvalidIdentifierException, ToolBoxException


_SKIP_PARAMS = {"self", "cls"}


# ======================================================
# | Helpers
# ======================================================

def _params_model_from_signature(func: Callable) -> type[BaseModel] | None:
    try:
        signature = inspect.signature(func)
        hints = get_type_hints(func, include_extras=True)
    except TypeError as exc:
        raise ToolBoxException(
            f"Could not resolve type hints for function '{func}': {exc}"
        ) from exc

    fields: dict[str, tuple[Any, Any]] = {}

    for name, param in signature.parameters.items():
        if name in _SKIP_PARAMS:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue # skips *args and **kwargs

        if name not in hints:
            raise ToolBoxException(
                f"Tool '{func.__qualname__}' parameter '{name}' has no type "
                "annotation; every tool parameter must be typed."
            )

        annotation = hints[name]
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, default)

    if not fields:
        return None # zero-arg tool

    model_name = "".join(part.title() for part in func.__name__.split("_")) + "Params"
    return create_model(model_name, __base__=BaseModel, **fields)

def _unwrap_optional(hint: Any) -> Any:
    """X | None / Optional[X] -> X. Leaves anything else untouched."""
    if get_origin(hint) is Union:
        non_none = [a for a in get_args(hint) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return hint

def _hint_matches(hint: Any, expected: type) -> bool:
    """Check if is subclass, safe against Optional[...] and generic aliases like dict[str, Any]."""
    if hint is None:
        return False
    hint = _unwrap_optional(hint)
    candidate = hint if inspect.isclass(hint) else get_origin(hint)
    if not inspect.isclass(candidate):
        return False
    try:
        return issubclass(candidate, expected)
    except TypeError:
        return False

def _first_typed_param(callable_obj: Callable, expected: type) -> tuple[str, Any] | None:
    """First non-skip, non-*args/**kwargs param of `callable_obj` whose annotation matches `expected`."""
    try:
        type_hints = get_type_hints(callable_obj)
    except TypeError:
        type_hints = {}

    try:
        params = inspect.signature(callable_obj).parameters
    except TypeError:
        raise ToolBoxException("Argument is not callable")

    for p in params.values():
        if p.name in _SKIP_PARAMS:
            continue
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        hint = type_hints.get(p.name)
        if hint is not None and _hint_matches(hint, expected):
            return p.name, _unwrap_optional(hint)
    return None

def _coerce_to_dict(data: Any) -> dict:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="python")
    if isinstance(data, dict):
        return data
    raise ToolBoxException(f"Expected a dict or BaseModel, got {type(data).__name__}")

def _resolve_call_args(
    callable_obj: Callable,
    data: Any,
    model_type: type[BaseModel] | type[dict],
) -> tuple[tuple, dict]:
    """
    Decide how to call `callable_obj` with `data`, given the model/type it should conform to.

    - If `callable_obj` has a single param typed as (a subclass of) `model_type`,
      build/validate that type from `data` and pass it positionally.
    - Otherwise treat `data` as keyword arguments: coerce to a dict and pass as **kwargs.
    """
    if data is None:
        return (), {}

    match = _first_typed_param(callable_obj, model_type)

    if match is None:
        return (), _coerce_to_dict(data)

    _, hint = match

    if isinstance(data, hint):
        return (data,), {}

    if inspect.isclass(hint) and issubclass(hint, BaseModel):
        return (hint.model_validate(_coerce_to_dict(data)),), {}

    # hint matched but isn't a BaseModel (e.g. plain `dict`) — coerce and pass positionally
    return (_coerce_to_dict(data),), {}


# ======================================================
# | Classes
# ======================================================

class FunctionDefinition(BaseModel):

    name: str
    description: str
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False}
    )

    _parameters_model: Optional[type[BaseModel]] = PrivateAttr(default=None)

    @property
    def parameters_model(self) -> Optional[type[BaseModel]]:
        return self._parameters_model

    @parameters_model.setter
    def parameters_model(self, value: type[BaseModel]):
        self._parameters_model = value

    @classmethod
    def from_params_model(
        cls, name: str, description: str,
        params_model: type[BaseModel] | None
    ) -> "FunctionDefinition":
        if params_model is not None:
            schema = params_model.model_json_schema()
            schema.pop("title", None)
            schema.setdefault("additionalProperties", False)
        else:
            schema = {"type": "object", "properties": {}, "additionalProperties": False}
        instance = cls(name=name, description=description, parameters=schema)
        instance.parameters_model = params_model
        return instance


class ToolDefinition(BaseModel):

    name: str
    type: Literal["function"] = "function"
    function: FunctionDefinition

    _returns: type[BaseModel] | type[str] = PrivateAttr(default=str)

    @property
    def returns(self) -> type[BaseModel] | type[str]:
        return self._returns

    @returns.setter
    def returns(self, value: type[BaseModel] | type[str]):
        self._returns = value


class AttributeExposure(BaseModel):

    attr_name: str
    
    _attr_type: type | None = PrivateAttr(default=None)

    @property
    def attr_type(self) -> type | None:
        return self._attr_type

    @attr_type.setter
    def attr_type(self, value: type):
        self._attr_type = value


class ToolBoxDefinition(BaseModel):

    id: str
    settings_attr: str | None = None

    tools: dict[str, ToolDefinition] = Field(default_factory=dict)
    attributes: dict[str, AttributeExposure] = Field(default_factory=dict)

    _clazz: type | None = PrivateAttr(default=None)
    _settings_type: type[BaseModel] | type[dict] = PrivateAttr(default=dict)

    @property
    def clazz(self) -> type:
        if self._clazz is None:
            raise ToolBoxException(f"ToolBox '{self.id}' has no defined clazz")
        return self._clazz

    @clazz.setter
    def clazz(self, value: type):
        self._clazz = value

    @property
    def settings_type(self) -> type[BaseModel] | type[dict]:
        return self._settings_type

    @settings_type.setter
    def settings_type(self, value: type[BaseModel] | type[dict]):
        self._settings_type = value

    def create_toolbox(self, settings: Any = None) -> Any:
        result: Any = None

        if settings is None or self.settings_attr is not None:
            result = self.clazz()
        else:
            init_method = getattr(self.clazz, "__init__", object.__init__)
            args, kwargs = _resolve_call_args(init_method, settings, self.settings_type)
            result = self.clazz(*args, **kwargs)

        if settings is not None and self.settings_attr is not None:
            setattr(result, self.settings_attr, settings)

        def run_tool(tool_name: str, params: Any = None):
            tool_method = getattr(result, tool_name)
            tool_def: ToolDefinition = tool_method._tool_def

            if params is not None and tool_def.function.parameters_model is not None:
                args, kwargs = _resolve_call_args(tool_method, params, tool_def.function.parameters_model)
                return tool_method(*args, **kwargs)

            return tool_method()

        setattr(result, "run_tool", run_tool)

        return result


# ======================================================
# | Registry and decorators
# ======================================================

ToolBoxRegistry: dict[str, ToolBoxDefinition] = {}


def tool(params: type[BaseModel] | None = None, *, name: str | None = None):
    def decorator(func):
        func._tool_def = ToolDefinition(
            name=func.__name__,
            function=FunctionDefinition.from_params_model(
                name=name or func.__name__,
                description=(func.__doc__ or "").strip(),
                params_model=params or _params_model_from_signature(func),
            )
        )
        func._tool_def._returns = get_type_hints(func).get("return")
        return func
    return decorator


def toolbox(
    settings_type: type[BaseModel] | type[dict] = dict,
    *,
    name: str | None = None,
    settings_attr: str | None = None,
    expose: list[str] = [],
):
    exp_attrs = [*expose]
    def decorator(cls):
        toolbox_def = ToolBoxDefinition(
            id=name or cls.__qualname__,
            settings_attr=settings_attr,
        )
        toolbox_def.clazz=cls
        toolbox_def._settings_type=settings_type
        ToolBoxRegistry[toolbox_def.id] = toolbox_def

        for attr_name, attr_value in vars(cls).items():
            if hasattr(attr_value, "_tool_def"):
                tool_def: ToolDefinition = attr_value._tool_def
                toolbox_def.tools[tool_def.name] = tool_def

        type_hints = get_type_hints(cls)
        for exp_attr in exp_attrs:
            toolbox_def.attributes[exp_attr] = AttributeExposure(attr_name=exp_attr)
            if exp_attr in type_hints:
                toolbox_def.attributes[exp_attr].attr_type = type_hints[exp_attr]

        return cls
    return decorator


# ======================================================
# | Settings
# ======================================================

class ToolBoxSetUp(BaseDatorumSettings):

    id: str
    toolbox_id: str

    tools_enabled: list[str] = Field(default_factory=list)

    settings_port: InputPort = Field(default_factory=InputPort)
    logger_port: ResourcePort = Field(default_factory=ResourcePort)
    monitor_port: ResourcePort = Field(default_factory=ResourcePort)
    custom_ports: dict[str, CustomPort] = Field(default_factory=dict)


class ToolBoxCollection(BaseDatorumPersistentSettings):

    toolboxes: list[ToolBoxSetUp] = Field(default_factory=list)