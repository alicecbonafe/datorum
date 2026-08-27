import functools

import click

from datorum import DatorumBaseError


def cli_command(name=None, load_settings: bool = True, **click_kwargs):
    def decorator(func):
        func._is_cli_command = True
        func._cmd_name = name
        func._cmd_kwargs = click_kwargs
        func._load_settings = load_settings
        return func

    return decorator


class BaseCommandGroup(click.Group):
    """Base Group that automatically registers commands for methods decorated with `cli_command`.
    
    :param name: Group name, passed to `click.Group` constructor.
    :type name: str, optional
    """

    def __init__(self, name=None, **attrs):
        super().__init__(name=name, **attrs)

        # Inspect attributes
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if getattr(attr, "_is_cli_command", False):
                cmd_name = attr._cmd_name or attr_name
                cmd_kwargs = attr._cmd_kwargs
                should_load_settings = getattr(attr, "_load_settings", True)

                cmd = click.command(name=cmd_name, **cmd_kwargs)(attr)
                if should_load_settings:
                    cmd.callback = self._wrap_with_settings_loader(attr)
                else:
                    cmd.callback = attr

                self.add_command(cmd)

            elif isinstance(attr, click.Command):
                self.add_command(attr)

    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except DatorumBaseError as exc:
            raise click.ClickException(str(exc)) from exc

    @staticmethod
    def _wrap_with_settings_loader(bound_method):
        @functools.wraps(bound_method)
        def wrapper(*args, **kwargs):
            ctx = click.get_current_context(silent=True)
            if ctx and ctx.obj and hasattr(ctx.obj, "settings"):
                ctx.obj.settings.load_lazy()
                ctx.obj.load_custom_registry()
            return bound_method(*args, **kwargs)

        return wrapper
