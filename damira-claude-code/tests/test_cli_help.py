"""`damira <pass-through> -h` shows the subcommand's own help instead of an argparse error."""

import subprocess
import sys
from pathlib import Path

import pytest

DAMIRA = Path(__file__).resolve().parents[1] / "scripts" / "damira.py"


@pytest.mark.parametrize("cmd", ["lab", "workbook", "docx", "diagram"])
def test_pass_through_help(cmd):
    r = subprocess.run([sys.executable, str(DAMIRA), cmd, "-h"], capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    assert f"damira {cmd}" in out and "invalid choice" not in out and "unrecognized arguments" not in out
