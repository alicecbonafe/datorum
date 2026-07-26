import sys
from unittest.mock import patch
import pytest

from datorum.__main__ import main


def test_cli_help(capsys):
    with patch.object(sys, "argv", ["datorum", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower() or "help" in captured.out.lower()
