"""`damira init` sets up a workspace without ever clobbering the user's files."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "damira.py"


def run(tmp, *args):
    out = subprocess.run([sys.executable, str(SCRIPT), "init", "--dir", str(tmp), *args],
                         capture_output=True, text=True, check=True)
    return out.stdout


def test_creates_the_workspace(tmp_path):
    run(tmp_path, "--vendor", "Cisco", "--platform", "Core: Catalyst 9300, IOS-XE 17.9.4",
        "--environment", "production")
    for d in ("configs", "documents", "notes"):
        assert (tmp_path / d).is_dir()
    claude = (tmp_path / "CLAUDE.md").read_text()
    assert "- Vendors: Cisco" in claude and "Catalyst 9300, IOS-XE 17.9.4" in claude
    assert (tmp_path / "AGENTS.md").read_text() == claude  # default target writes both
    assert (tmp_path / "README.md").exists()


def test_configs_are_kept_out_of_git(tmp_path):
    run(tmp_path)
    assert (tmp_path / "configs" / ".gitignore").read_text().splitlines()[-2:] == ["*", "!.gitignore"]


def test_rerun_replaces_only_its_own_block(tmp_path):
    run(tmp_path, "--target", "claude", "--vendor", "Cisco")
    path = tmp_path / "CLAUDE.md"
    path.write_text("# Our team rules\nNever reboot before 22:00.\n\n" + path.read_text()
                    + "\n## Our own notes\nKeep me.\n")
    run(tmp_path, "--target", "claude", "--vendor", "Juniper")
    text = path.read_text()
    assert "Never reboot before 22:00." in text and "Keep me." in text
    assert "- Vendors: Juniper" in text and "- Vendors: Cisco" not in text
    assert text.count("<!-- damira:begin -->") == 1


def test_existing_instructions_file_is_appended_to_not_replaced(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Existing project rules\nUse tabs.\n")
    (tmp_path / "README.md").write_text("my readme\n")
    run(tmp_path, "--target", "cursor")
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("# Existing project rules\nUse tabs.\n")
    assert "<!-- damira:begin -->" in text
    assert (tmp_path / "README.md").read_text() == "my readme\n"
    assert not (tmp_path / "CLAUDE.md").exists()


def test_no_answers_leaves_a_prompt_to_fill_them_in(tmp_path):
    run(tmp_path, "--target", "claude")
    assert "Re-run `damira init`" in (tmp_path / "CLAUDE.md").read_text()
