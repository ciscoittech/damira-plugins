"""#498: mechanical steps run on a cheap model, and every skill is cheap-model ready.

A cheap model follows numbered steps with exact commands well and improvises badly, so
the lint checks structure, not prose quality.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "composer-2"
AGENTS = {"damira-renderer", "damira-fixer"}
# Cursor subagents accept name, description, model, readonly, is_background only.
IGNORED = {"permissionMode", "hooks", "mcpServers", "initialPrompt", "tools"}
DELEGATING = ["generate-workbook", "generate-playbook", "generate-config", "generate-automation",
              "generate-terraform", "generate-tests", "generate-pipeline", "upgrade-plan"]


def _frontmatter(path):
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path.name}: no frontmatter"
    return dict(re.findall(r"^([A-Za-z]\w*):\s*(.*)$", m.group(1), re.M))


def test_agents_pin_a_cheap_model_without_ignored_fields():
    agents = {p.stem: p for p in (ROOT / "agents").glob("*.md")}
    assert AGENTS <= set(agents)
    for name, path in agents.items():
        fm = _frontmatter(path)
        assert fm.get("name") == name and fm.get("description"), name
        assert fm.get("model") == MODEL, name
        assert not IGNORED & set(fm), name
        assert "mcp__" not in fm.get("tools", ""), f"{name}: evidence gathering stays on the parent"


def test_every_skill_passes_the_readiness_lint():
    for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
        text = skill.read_text()
        name = skill.parent.name
        steps = re.findall(r"^#{2,3} Step \d+[a-z]?:", text, re.M)
        assert len(steps) >= 2, f"{name}: needs numbered '## Step N:' headings"
        assert re.search(r"^\s*```(bash|sh)\n", text, re.M), f"{name}: needs a fenced command"
        assert re.search(r"^#{2,3} Step \d+[a-z]?:.*(present|report|hand back|summar|document)",
                         text, re.M | re.I), f"{name}: needs an output/present step"
        assert len(text.splitlines()) <= 130, f"{name}: move long prose into references/"


def test_script_heavy_skills_delegate_to_the_cheap_agents():
    for name in DELEGATING:
        text = (ROOT / "skills" / name / "SKILL.md").read_text()
        assert "damira-renderer" in text or "damira-fixer" in text, name
