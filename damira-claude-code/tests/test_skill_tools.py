"""Every skill's allowed-tools entry must name a tool the bundled server exposes.

Installed as a plugin, Claude Code registers the server's tools as
mcp__plugin_damira_damira__<tool>. The skills pre-approved mcp__damira__<tool>, which
matches nothing in a plugin install, so every Damira call still prompted (and was
denied outright in headless runs).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp"))
sys.path.insert(0, str(ROOT / "scripts"))

import server  # noqa: E402

CATALOG = {t["name"] for t in server.TOOLS}
PLUGIN_PREFIX = "mcp__plugin_damira_damira__"


def _allowed_tools():
    for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
        m = re.search(r"^allowed-tools: (.+)$", skill.read_text(), re.M)
        if m:
            yield skill.parent.name, [n.strip() for n in m.group(1).split(",")]


def test_every_allowed_tool_exists_in_the_bundled_server():
    for skill, names in _allowed_tools():
        for name in names:
            tool = name.rsplit("__", 1)[-1]
            assert tool in CATALOG, f"{skill}: {name} is not a tool the server exposes"


def test_every_skill_pre_approves_the_plugin_installed_names():
    for skill, names in _allowed_tools():
        assert any(n.startswith(PLUGIN_PREFIX) for n in names), skill
        for name in names:
            if name.startswith("mcp__damira__"):
                assert PLUGIN_PREFIX + name.rsplit("__", 1)[-1] in names, f"{skill}: {name}"
