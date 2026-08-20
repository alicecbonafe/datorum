import click
from datorum.cli.commands.base import BaseCommandGroup


def test_base_command_group_accepts_plain_click_command():
    """Cover the `elif isinstance(attr, click.Command):` line in
    `BaseCommandGroup.__init__`, ensuring that native Click commands
    are also added to the group."""
    
    class MyGroup(BaseCommandGroup):
        def __init__(self, name=None, **attrs):
            super().__init__(name=name, **attrs)

        @click.command("manual_cmd")
        def manual_cmd():
            """A standard Click command, without @cli_command."""
            pass

    group = MyGroup()
    # The command must have been registered in the group.
    assert "manual_cmd" in group.commands
    assert isinstance(group.commands["manual_cmd"], click.Command)