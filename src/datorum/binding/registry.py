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
    """Register a resource factory function.

    :param name: Unique name for the resource factory.
    :type name: str
    :param factory: Factory callable.
    :type factory: collections.abc.Callable
    :param force: Overwrite existing factory, defaults to False.
    :type force: bool, optional
    :returns: Registered factory callable, or `None` if `name` is registered and `force` is false.
    :rtype: collections.abc.Callable | None
    :raises ResourceFactoryError: If signature invalid.
    """
    if name in ResourceFactoryRegistry and not force:
        return None

    if not validate_factory_signature(factory):
        raise ResourceFactoryError(
            f"Resource factory '{name}' has not a compatible signature"
        )
    ResourceFactoryRegistry[name] = factory
    return factory


def get_resource_factory(factory_name: str) -> Callable:
    """Retrieve a registered resource factory function by name.
    
    :param factory_name: Factory name identifier.
    :type factory_name: str
    :returns: Factory callable.
    :rtype: collections.abc.Callable
    :raises ResourceFactoryError: If factory is not registered.
    """

    if factory_name not in ResourceFactoryRegistry:
        raise ResourceFactoryError(f"Resource factory '{factory_name}' not found")
    return ResourceFactoryRegistry[factory_name]


def resource(name: str | None = None, force: bool = False):
    """Decorator to register a resource factory callable.

    :param name: Factory name override.
    :type name: str | None, optional
    :param force: Overwrite existing factory registration, defaults to False.
    :type force: bool, optional
    """
    def decorator(func):
        factory_name = name or func.__name__
        return register_resource_factory(
            name=factory_name,
            factory=func,
            force=force,
        )

    return decorator
