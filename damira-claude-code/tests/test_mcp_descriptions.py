"""MCP tool descriptions stay calm and make no promises the backend does not keep (#579)."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import server  # noqa: E402

ACRONYMS = {"CVE", "NVD", "CLI", "BGP", "OSPF", "IOS", "MOP", "CCIE", "NTP", "SNMP", "HTTP"}


def test_descriptions_have_no_all_caps_directives():
    for tool in server.TOOLS:
        for word in re.findall(r"\b[A-Z]{4,}\b", tool["description"]):
            assert word in ACRONYMS, f"{tool['name']}: {word}"


def test_troubleshoot_does_not_claim_to_gather_evidence():
    tool = next(t for t in server.TOOLS if t["name"] == "damira_troubleshoot")
    assert "gathers evidence" not in tool["description"]
