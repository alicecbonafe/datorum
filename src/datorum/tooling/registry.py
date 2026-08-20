import inspect
import types
import uuid
from collections.abc import Callable
from typing import (
    Any,
    Literal,
    Protocol,
    Self,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    runtime_checkable,
)

from pydantic import BaseModel, Field, PrivateAttr, create_model

from ..binding.settings import ContextBindType
from .exceptions import ToolBoxRegistryError

# ======================================================
# | Helpers
# ======================================================

_SKIP_PARAMS = {"self", "cls"}

def _params_model_from_signature(func: Callable, name: str | None = None) -> type[BaseModel] | None:
    if not name:
        if hasattr(func, "__name__"):
            name = func.__name__
        else:
            name = f"anonymous_{uuid.uuid4().hex[:6]}"
    try:
        signature = inspect.signature(func)
        if callable(func) and not (
            inspect.isfunction(func)
            or inspect.ismethod(func)
            or inspect.isclass(func)
        ):
            hints = get_type_hints(func.__call__, include_extras=True)
        else:
            hints = get_type_hints(func, include_extras=True)

    except (TypeError, NameError) as exc:
        raise ToolBoxRegistryError(
            f"Could not resolve type hints for function '{func}': {exc}"
        ) from exc

    fields: dict[str, tuple[type, Any]] = {}

    for name, param in signature.parameters.items():
        if name in _SKIP_PARAMS:
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue  # skips *args and **kwargs

        if name not in hints:
            tool_name = func.__name__ if hasattr(func, "__name__") else "anonymous"
            raise ToolBoxRegistryError(
                f"Tool '{tool_name}' parameter '{name}' has no type "
                "annotation; every tool parameter must be typed."
            )

        annotation = hints[name]
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, default)

    if not fields:
        return None  # zero-arg tool
    
    if len(fields) == 1:
        single_type = next(iter(fields.values()))[0]
        unwrapped = _unwrap_optional(single_type)
        if inspect.isclass(unwrapped) and issubclass(unwrapped, BaseModel):
            return unwrapped

    model_name = "".join(part.title() for part in func.__name__.split("_")) + "Params"
    return create_model(model_name, __base__=BaseModel, **fields)  # type: ignore[call-overload]


def _unwrap_optional(hint: Any) -> Any:
    """X | None / Optional[X] -> X. Leaves anything else untouched."""
    if get_origin(hint) is Union:
        non_none = [a for a in get_args(hint) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return hint


def _is_optional(hint: Any) -> bool:
    origin = get_origin(hint)
    if origin in (Union, types.UnionType):
        args = get_args(hint)
        return type(None) in args
    return False


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


def _first_typed_param(
    callable_obj: Callable, expected: type
) -> tuple[str, Any] | None:
    """First non-skip, non-*args/**kwargs param of `callable_obj` whose annotation matches `expected`."""
    try:
        type_hints = get_type_hints(callable_obj)
    except (TypeError, NameError):
        type_hints = {}

    try:
        params = inspect.signature(callable_obj).parameters
    except TypeError:
        raise ToolBoxRegistryError("Argument is not callable")

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
    raise ToolBoxRegistryError(f"Expected a dict or BaseModel, got {type(data).__name__}")


def _resolve_call_args(
    callable_obj: Callable,
    data: Any,
    model_type: type[BaseModel | dict],
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

@runtime_checkable
class ToolBox(Protocol):
    def get_toolbox_definition() -> ToolBoxDefinition:...
    async def run_tool(self, tool_name: str, params: Any = None):...

class FunctionDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    _parameters_model: type[BaseModel] | None = PrivateAttr(default=None)

    @property
    def parameters_model(self) -> type[BaseModel] | None:
        return self._parameters_model

    @parameters_model.setter
    def parameters_model(self, value: type[BaseModel]):
        self._parameters_model = value

    @classmethod
    def from_params_model(
        cls, name: str, description: str, params_model: type[BaseModel] | None
    ) -> FunctionDefinition:
        if params_model is not None:
            schema = params_model.model_json_schema()
            schema.pop("title", None)
            schema.setdefault("additionalProperties", False)
        else:
            schema = {"type": "object", "properties": {}, "additionalProperties": False}
        instance = cls(name=name, description=description, parameters=schema)
        if params_model is not None:
            instance.parameters_model = params_model
        return instance


class ToolDefinition(BaseModel):
    name: str
    function: FunctionDefinition

    _returns: type[BaseModel] | type[str] = PrivateAttr(default=str)

    @property
    def returns(self) -> type[BaseModel] | type[str]:
        return self._returns

    @returns.setter
    def returns(self, value: type[BaseModel] | type[str]):
        self._returns = value

    type: Literal["function"] = "function"  # OpenAI API protocol compatibility


class BaseToolBoxField(BaseModel):
    field_type: str
    name: str | None = None
    attr_name: str | None = None
    description: str | None = None
    required: bool | None = None

class ContextField(BaseToolBoxField):
    field_type: Literal["context"] = "context"
    context_bind_type: ContextBindType = Field(default=ContextBindType.model)

class ResourceField(BaseToolBoxField):
    field_type: Literal["resource"] = "resource"


class ToolBoxDefinition(BaseModel):
    name: str
    tools: dict[str, ToolDefinition] = Field(default_factory=dict)
    context_fields: dict[str, ContextField] = Field(default_factory=dict)
    resource_fields: dict[str, ResourceField] = Field(default_factory=dict)
    clazz: type[Any] = Field(default=None, exclude=True)

    def create_toolbox(self) -> ToolBox:
        result: Any = self.clazz()

        def get_toolbox_definition() -> Self:
            return self

        async def run_tool(tool_name: str, params: Any = None):
            missing_fields: list[str] = []
            for field in self.context_fields.values():
                val = getattr(result, field.attr_name, None)
                if field.required and (val is None or isinstance(val, BaseToolBoxField)):
                    missing_fields.append(f"ctx:{field.name}")
            for field in self.resource_fields.values():
                val = getattr(result, field.attr_name, None)
                if field.required and (val is None or isinstance(val, BaseToolBoxField)):
                    missing_fields.append(f"res:{field.name}")
            if len(missing_fields) > 0:
                raise ToolBoxRegistryError(f"Missing required field(s): {missing_fields}")

            tool_method = getattr(result, tool_name)
            tool_def: ToolDefinition = tool_method._tool_def

            if params is not None and tool_def.function.parameters_model is not None:
                args, kwargs = _resolve_call_args(
                    tool_method, params, tool_def.function.parameters_model
                )
                res = tool_method(*args, **kwargs)
            else:
                res = tool_method()

            if inspect.isawaitable(res):
                return await res
            return res

        result.get_toolbox_definition = get_toolbox_definition
        result.run_tool = run_tool

        return result


# ======================================================
# | Registry and decorators
# ======================================================

ToolBoxRegistry: dict[str, ToolBoxDefinition] = {}

def get_toolbox_definition(toolbox_name: str) -> ToolBoxDefinition:
    if toolbox_name not in ToolBoxRegistry:
        raise ToolBoxRegistryError(f"ToolBox '{toolbox_name}' not found")
    return ToolBoxRegistry[toolbox_name]

def tool(name: str | None = None, params: type[BaseModel] | None = None):
    def decorator(func):
        func._tool_def = ToolDefinition(
            name=name or func.__name__,
            function=FunctionDefinition.from_params_model(
                name=name or func.__name__,
                description=(func.__doc__ or "").strip(),
                params_model=params or _params_model_from_signature(func, name),
            ),
        )
        func._tool_def._returns = get_type_hints(func).get("return")
        return func

    return decorator

def toolbox(name: str | None = None, force: bool = False):
    def decorator(cls):
        toolbox_name = name or cls.__name__
        if toolbox_name in ToolBoxRegistry and not force:
            raise ToolBoxRegistryError(f"ToolBox '{toolbox_name}' is already registered, use 'force=True' to overwrite")
        toolbox_def = ToolBoxDefinition(name=name or cls.__name__)
        toolbox_def.clazz = cls
        ToolBoxRegistry[toolbox_def.name] = toolbox_def

        try:
            type_hints = get_type_hints(cls)
        except (TypeError, NameError):
            type_hints = {}

        for attr_name, attr_value in vars(cls).items():
            if hasattr(attr_value, "_tool_def"):
                tool_def: ToolDefinition = attr_value._tool_def
                if tool_def.name in toolbox_def.tools:
                    raise ToolBoxRegistryError(f"Tool '{tool_def.name}' is already registered in ToolBox '{toolbox_name}'")
                toolbox_def.tools[tool_def.name] = tool_def
            elif isinstance(attr_value, ContextField):
                if attr_value.name in toolbox_def.context_fields:
                    raise ToolBoxRegistryError(f"Field '{attr_value.name}' is already registered in ToolBox '{toolbox_name}'")
                attr_value.attr_name = attr_name
                attr_value.name = attr_value.name or attr_name
                if attr_value.required is None:
                    if attr_name in type_hints:
                        attr_value.required = not _is_optional(type_hints[attr_name])
                    else:
                        attr_value.required = False
                toolbox_def.context_fields[attr_value.name] = attr_value
            elif isinstance(attr_value, ResourceField):
                if attr_value.name in toolbox_def.resource_fields:
                    raise ToolBoxRegistryError(f"Field '{attr_value.name}' is already registered in ToolBox '{toolbox_name}'")
                attr_value.attr_name = attr_name
                attr_value.name = attr_value.name or attr_name
                if attr_value.required is None:
                    if attr_name in type_hints:
                        attr_value.required = not _is_optional(type_hints[attr_name])
                    else:
                        attr_value.required = False
                toolbox_def.resource_fields[attr_value.name] = attr_value

        for field in toolbox_def.context_fields.values():
            setattr(cls, field.attr_name, None)
        for field in toolbox_def.resource_fields.values():
            setattr(cls, field.attr_name, None)

        return cls

    return decorator

