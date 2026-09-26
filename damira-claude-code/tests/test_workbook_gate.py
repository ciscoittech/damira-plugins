"""#484 T6 — the document gate adds a grounding note when a workbook spec is written.

It notes; it never blocks and never takes a permission decision on a grounded session
(the evidence check in test_hooks.py still owns that).
"""

import json
import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent / "hooks-handlers" / "document_gate.py"

GROUNDED_LINE = json.dumps({"type": "tool_result", "name": "mcp__damira__damira_search_release_notes",
                            "content": "17.9.5 caveats: run show version first."})

SPEC = {"title": "t", "sheets": [{"name": "Pre-Checks", "headers": ["Step", "CLI Command"], "rows": [
    {"step": "a", "cli_command": "show version"},
    {"step": "b", "cli_command": "request platform magic-fix all"},
]}]}


def _run(tmp_path, content):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(GROUNDED_LINE + "\n", encoding="utf-8")
    change = tmp_path / "documents" / "chg-001"
    (change / "evidence").mkdir(parents=True)
    (change / "evidence" / "notes.md").write_text("run show version first", encoding="utf-8")
    event = {"tool_name": "Write", "transcript_path": str(transcript),
             "tool_input": {"file_path": str(change / "workbook.json"), "content": content}}
    proc = subprocess.run([sys.executable, str(GATE)], input=json.dumps(event),
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, timeout=30)
    return proc.returncode, proc.stdout


def test_unbacked_workbook_cell_gets_a_note_not_a_block(tmp_path):
    code, out = _run(tmp_path, json.dumps(SPEC))
    assert code == 0
    msg = json.loads(out)
    assert "permissionDecision" not in msg.get("hookSpecificOutput", {})
    assert "1 of 2" in msg["systemMessage"] and "UNVERIFIED" in msg["systemMessage"]


def test_unparseable_workbook_spec_is_left_alone(tmp_path):
    code, out = _run(tmp_path, "{not json")
    assert code == 0 and out.strip() == ""
