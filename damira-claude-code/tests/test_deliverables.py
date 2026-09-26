"""#484 T1 — server deliverables[] are no longer dropped by call().

chat-sync passes the agent JSON through unchanged, so a deliverable arrives either as a
top-level `deliverables` entry or as a `role: "deliverable"` message. Both shapes land in
documents/<id>/ when the workspace has a documents/ folder, and are inlined otherwise
(the MCP server in Claude Desktop has no workspace to write into). Mocks urllib.
"""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import damira  # noqa: E402


def _fake_response(payload):
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    return cm


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DAMIRA_API_KEY", "dm_pro_test")  # no demo prefix in the reply
    monkeypatch.chdir(tmp_path)


def test_top_level_deliverables_are_saved_under_documents_and_listed(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    monkeypatch.setenv("DAMIRA_CHANGE_ID", "chg-042")
    payload = {"response": "Plan ready.", "deliverables": [
        {"filename": "ios-xe-upgrade.damira.json", "content": '{"sheets": []}', "type": "spreadsheet"},
        {"filename": "../../etc/evil.md", "content": "# MOP", "type": "docs"},
    ]}
    with mock.patch("urllib.request.urlopen", return_value=_fake_response(payload)):
        out = damira.call("Plan an upgrade", {"mcp_tool": "upgrade_plan"})

    folder = tmp_path / "documents" / "chg-042"
    assert (folder / "ios-xe-upgrade.damira.json").read_text() == '{"sheets": []}'
    assert (folder / "evil.md").read_text() == "# MOP", "path traversal stripped to a basename"
    assert not (tmp_path.parent / "etc" / "evil.md").exists()
    assert out.startswith("Plan ready.")
    assert "documents/chg-042/ios-xe-upgrade.damira.json" in out
    assert "documents/chg-042/evil.md" in out


def test_message_shape_is_deduplicated_and_inlined_without_a_documents_folder(tmp_path):
    d = {"filename": "runbook.md", "content": "# Runbook\nstep 1", "type": "docs"}
    payload = {"response": "Done.", "deliverables": [d],
               "messages": [{"role": "assistant", "content": "Done."}, {"role": "deliverable", **d}]}
    with mock.patch("urllib.request.urlopen", return_value=_fake_response(payload)):
        out = damira.call("x", {"mcp_tool": "agent"})

    assert not (tmp_path / "documents").exists(), "never create documents/ uninvited"
    assert out.count("# Runbook\nstep 1") == 1
    assert "runbook.md" in out


def test_answer_without_deliverables_is_unchanged():
    with mock.patch("urllib.request.urlopen", return_value=_fake_response({"response": "Plain answer."})):
        assert damira.call("x", {"mcp_tool": "agent"}) == "Plain answer."


def test_save_does_not_follow_a_planted_symlink(tmp_path, monkeypatch):
    import deliverables
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(deliverables.CHANGE_ENV, "chg-1")
    folder = tmp_path / "documents" / "chg-1"
    folder.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    (folder / "mop.md").symlink_to(outside)  # dangling: outside.md does not exist yet
    deliverables.save([{"filename": "mop.md", "content": "hello", "type": "mop"}])
    assert not outside.exists()
    assert (folder / "mop-2.md").read_text(encoding="utf-8") == "hello"
