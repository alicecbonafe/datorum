import functools

import click

from datorum import DatorumBaseError

from .bindings import BindingSyntaxError


def handle_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (DatorumBaseError, BindingSyntaxError) as exc:
            raise click.ClickException(str(exc)) from exc
    return wrapper