"""#561 decision 4: Cursor equivalent of Claude Code's implicit /damira:<skill>.

Cursor plugins auto-discover a `commands/` directory of markdown files, each
becoming an explicit `/<name>` entry point (see
dev/active/cursor-3x-damira/cursor-3x-capability-map.md). MVP coverage: the
four user-facing skills each have a command file with a description and a
pointer at the skill they invoke.
"""

from pathlib import Path

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"

_EXPECTED = {
    "troubleshoot": "troubleshoot",
    "upgrade-plan": "upgrade-plan",
    "config-audit": "config-audit",
    "generate-config": "generate-config",
}


def _frontmatter(path: Path) -> dict:
    """Parse the flat `key: value` frontmatter these command files use.

    Plugins are stdlib-only by design (CI's Test (Plugins) job installs only
    pytest — see plugins/damira-cursor/tests/test_validate.py's
    pytest.importorskip("yaml") for the same constraint), so this avoids an
    unconditional `import yaml` for what is just single-line key/value pairs.
    """
    text = path.read_text()
    assert text.startswith("---\n"), f"{path.name} missing frontmatter"
    end = text.index("\n---", 4)
    fields = {}
    for line in text[4:end].splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_commands_dir_exists():
    assert COMMANDS_DIR.is_dir()


def test_each_expected_command_file_exists():
    for name in _EXPECTED:
        assert (COMMANDS_DIR / f"{name}.md").exists(), f"missing commands/{name}.md"


def test_each_command_has_a_description():
    for name in _EXPECTED:
        fm = _frontmatter(COMMANDS_DIR / f"{name}.md")
        assert fm.get("description"), f"{name}.md has no description"


def test_each_command_body_names_its_skill():
    for name, skill in _EXPECTED.items():
        body = (COMMANDS_DIR / f"{name}.md").read_text()
        assert skill in body, f"{name}.md never names the `{skill}` skill it invokes"
