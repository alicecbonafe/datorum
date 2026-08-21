import inspect
import types
from collections.abc import Callable
from typing import (
    Any,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from .exceptions import ResourceFactoryError


def validate_factory_signature(func: Callable) -> bool:
    signature = inspect.signature(func)
    params = signature.parameters

    for param in params.values():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            return False

    if any(
        p.kind == inspect.Parameter.KEYWORD_ONLY
        and p.default is inspect.Parameter.empty
        for p in params.values()
    ):
        return False

    pos_params = [
        p
        for p in params.values()
        if p.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.default is inspect.Parameter.empty
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
    if origin in (Union, types.UnionType):
        args = get_args(param_type)
    else:
        args = None

    if args is None:
        return False

    expected_types = (str, type(None))
    for exp in expected_types:
        if not any(issubclass(exp, arg) for arg in args):
            return False

    return True


ResourceFactoryRegistry: dict[str, Callable] = {}


def register_resource_factory(
    name: str, factory: Callable, force: bool = False
) -> Callable | None:
    if name in ResourceFactoryRegistry and not force:
        return None
        # raise ResourceFactoryError(
        #     f"Resource factory '{name}' is already registered, use 'force=True' to overwrite")
    if not validate_factory_signature(factory):
        raise ResourceFactoryError(
            f"Resource factory '{name}' has not a compatible signature"
        )
    ResourceFactoryRegistry[name] = factory
    return factory


def get_resource_factory(factory_name: str) -> Callable:
    if factory_name not in ResourceFactoryRegistry:
        raise ResourceFactoryError(f"Resource factory '{factory_name}' not found")
    return ResourceFactoryRegistry[factory_name]


def resource(name: str | None = None, force: bool = False):
    def decorator(func):
        factory_name = name or func.__name__
        return register_resource_factory(
            name=factory_name,
            factory=func,
            force=force,
        )

    return decorator
