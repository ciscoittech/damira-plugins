import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "hooks-handlers" / "device_gate.py"


@pytest.mark.parametrize("tool", ["ssh_command", "mcp__damira__network_device_command"])
def test_gate_denies_device_mcp_tools_in_advisor(tool):
    proc = subprocess.run([sys.executable, str(GATE)], input=json.dumps({"tool_name": tool}),
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert json.loads(proc.stdout)["permission"] == "deny"
