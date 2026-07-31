from abc import ABC
import inspect
from logging import Logger
from typing import (
    Any,
    Callable,
    ClassVar,
    Literal,
    Optional,
    get_type_hints
)

from pydantic import BaseModel, Field, PrivateAttr, create_model, model_validator

from .. import get_logger
from ..exceptions import InvalidIdentifierException
from ..model.pipeline import ToolBoxSettings


ToolBoxRegistry: dict[str, "BaseToolBox"] = {}


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
        instance._parameters_model = params_model
        return instance


class ToolDefinition(BaseModel):

    type: Literal["function"] = "function"
    function: FunctionDefinition

    _callable: Optional[Callable] = PrivateAttr(default=None)
    _returns: type[BaseModel] | type[str] = PrivateAttr(default=str)

    @property
    def callable(self) -> Callable:
        if self._callable is None:
            raise ValueError("Callable not defined for this tool")
        return self._callable

    @property
    def returns(self) -> type[BaseModel] | type[str]:
        return self._returns


_SKIP_PARAMS = {"self", "cls"}

def _params_model_from_signature(func: Callable) -> type[BaseModel] | None:
    signature = inspect.signature(func)
    try:
        hints = get_type_hints(func, include_extras=True)
    except NameError as exc:
        raise TypeError(
            f"Could not resolve type hints for tool '{func.__qualname__}': {exc}"
        ) from exc

    fields: dict[str, tuple[Any, Any]] = {}

    for name, param in signature.parameters.items():
        if name in _SKIP_PARAMS:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue # skips *args and **kwargs

        if name not in hints:
            raise TypeError(
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


def tool(params: type[BaseModel] | None = None, *, name: str | None = None):
    def decorator(func):
        return_hint = get_type_hints(func).get("return")
        returns: type[BaseModel] | None = None
        if isinstance(return_hint, type) and issubclass(return_hint, BaseModel):
            returns = return_hint
        elif return_hint is not str:
            raise TypeError(f"Tool '{func.__qualname__}' must return a BaseModel subclass or str.")

        func._tool_def = ToolDefinition(
            function=FunctionDefinition.from_params_model(
                name=name or func.__name__,
                description=(func.__doc__ or "").strip(),
                params_model=params or _params_model_from_signature(func),
            )
        )
        if returns is not None:
            func._tool_def._returns = returns
        return func
    return decorator


class BaseToolBox(ABC):

    toolbox_id: ClassVar[str]
    settings_model: ClassVar[type[BaseModel] | None] = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if getattr(cls, "toolbox_id", None):
            ToolBoxRegistry[cls.toolbox_id] = cls

    def __init__(self, id: str, settings: dict[str, Any] | None = None):
        self.id = id
        self.settings = self.settings_model.model_validate(settings or {}) \
            if self.settings_model else None

        self._loaded: bool = False
        self._tools : dict[str, ToolDefinition] = {}
        self._logger: Logger | None = None

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = get_logger(self.id)
        return self._logger

    def get_tool(self, tool_id):
        if not self._loaded:
            self._load_tools()
        if tool_id not in self._tools:
            raise InvalidIdentifierException(f"No tool '{tool_id}' in toolbox '{self.id}'")
        return self._tools[tool_id]

    def _load_tools(self):
        for cls in reversed(type(self).__mro__):
            for key, val in cls.__dict__.items():
                tool_def = getattr(val, "_tool_def", None)
                if isinstance(tool_def, ToolDefinition):
                    bound = tool_def.model_copy(deep=False)
                    bound._callable = getattr(self, key)
                    self._tools[tool_def.function.name] = bound
        self._loaded = True

    
def build_toolbox(config: ToolBoxSettings) -> BaseToolBox:
    cls = ToolBoxRegistry[config.toolbox]
    return cls(id=config.id, settings=config.settings)
