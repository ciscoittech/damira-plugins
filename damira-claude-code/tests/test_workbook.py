"""#484 — workbook renderer, static preview and grounding check.

The xlsx is inspected as a zip (stdlib), so these run without openpyxl in the test
interpreter; rendering itself needs openpyxl or uv and is skipped when neither exists.
Nothing writes to the real ~/.damira: DAMIRA_LOG_DIR and HOME point at tmp.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parent.parent
_SCRIPTS = _PLUGIN / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import render_workbook  # noqa: E402
import workbook_grounding  # noqa: E402

EVIDENCE = "Release notes 17.9.5: run `show version` and `show install summary` before activating."

SPEC = {
    "title": "IOS-XE 17.6 to 17.9 Upgrade",
    "summary_fields": {"Product": "IOS-XE", "Engineer": "[YOUR NAME]"},
    "executive_summary": "Upgrade 40 access switches.",
    "sheets": [
        {
            "name": "Pre-Checks",
            "headers": ["#", "Task", "CLI Command", "Expected Result", "Pass?"],
            "rows": [
                {"task": "Record version", "cli_command": "show version", "expected_result": "17.6.5"},
                {"task": "Install state", "cli_command": "show install summary", "expected_result": "C"},
                {"task": "Invented step", "cli_command": "request platform magic-fix all",
                 "expected_result": "<script>alert(1)</script>"},
                {"task": "[VERIFY] licence", "cli_command": "[VERIFY: licence command]"},
            ],
            "input_columns": ["Pass?"],
            "dropdowns": {"Pass?": "Pass,Fail"},
            "conditional_rules": [{"column": "Pass?", "type": "pass_fail"}],
            "auto_id_prefix": "PRE",
        },
        {
            "name": "Implementation Steps",
            "headers": ["#", "Step", "Command", "Duration (min)", "Buffer", "Total", "Status"],
            "rows": [{"step": "Activate", "command": "show version", "duration_(min)": "20", "buffer": "5"}],
            "formulas": {"Total": "={Duration (min)}+{Buffer}"},
            "dropdowns": {"Status": "Not Started,In Progress,Complete,Failed"},
            "conditional_rules": [{"column": "Status", "type": "status"}],
        },
    ],
}


@pytest.fixture(autouse=True)
def _private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _change_dir(tmp_path: Path, evidence: str = EVIDENCE) -> Path:
    change = tmp_path / "documents" / "chg-001"
    (change / "evidence").mkdir(parents=True)
    (change / "workbook.json").write_text(json.dumps(SPEC), encoding="utf-8")
    if evidence:
        (change / "evidence" / "release-notes.md").write_text(evidence, encoding="utf-8")
    return change


def test_grounding_flags_unbacked_command_and_never_rewrites_it():
    tagged, unverified, checked = workbook_grounding.ground_spec(SPEC, EVIDENCE)
    rows = tagged["sheets"][0]["rows"]
    assert [r.get("grounding") for r in rows] == [
        "source-matched", "source-matched", "UNVERIFIED", None,  # [VERIFY is honest self-flagging
    ]
    assert rows[2]["cli_command"] == "request platform magic-fix all"
    assert "Grounding" in tagged["sheets"][0]["headers"]
    assert (unverified, checked) == (1, 4)
    assert "UNVERIFIED" in tagged["executive_summary"]
    assert "Grounding" not in SPEC["sheets"][0]["headers"], "input spec must not be mutated"


def test_preview_html_is_self_contained_and_escaped(tmp_path):
    change = _change_dir(tmp_path)
    result = render_workbook.render(change / "workbook.json", xlsx=False)
    page = (change / "index.html").read_text(encoding="utf-8")

    assert result["html"] == change / "index.html"
    for sheet in ("Summary", "Pre-Checks", "Implementation Steps"):
        assert sheet in page
    assert "UNVERIFIED" in page
    assert "<script>alert(1)</script>" not in page, "cell text must be escaped"
    # No external assets: nothing fetched from anywhere when the file is opened.
    assert not re.search(r"""\bsrc\s*=\s*["']?(https?:)?//""", page, re.I)
    assert not re.search(r"""<link\b[^>]*href\s*=\s*["']?(https?:)?//""", page, re.I)
    assert not re.search(r"""url\(\s*["']?(https?:)?//""", page, re.I)
    assert "@import" not in page


def _can_render_xlsx() -> bool:
    return importlib.util.find_spec("openpyxl") is not None or shutil.which("uv") is not None


@pytest.mark.skipif(not _can_render_xlsx(), reason="needs openpyxl or uv")
def test_xlsx_has_summary_sheets_validation_formatting_and_filters(tmp_path):
    change = _change_dir(tmp_path)
    env = {**os.environ, "DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home")}
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "damira.py"), "workbook", str(change / "workbook.json")],
        capture_output=True, text=True, env=env, timeout=240,
    )
    assert proc.returncode == 0, proc.stderr
    xlsx = change / "workbook.xlsx"
    assert xlsx.is_file()
    assert "UNVERIFIED" in proc.stdout

    with zipfile.ZipFile(xlsx) as z:
        book = z.read("xl/workbook.xml").decode()
        names = re.findall(r'<sheet [^>]*name="([^"]+)"', book)
        assert names == ["Summary", "Pre-Checks", "Implementation Steps"]
        pre = z.read("xl/worksheets/sheet2.xml").decode()
        impl = z.read("xl/worksheets/sheet3.xml").decode()
    assert "<dataValidation" in pre and "Pass,Fail" in pre
    assert "<conditionalFormatting" in pre and "<conditionalFormatting" in impl
    assert 'topLeftCell="A2"' in pre and 'state="frozen"' in pre
    assert "<autoFilter" in pre
    assert "<f>D2+E2</f>" in impl, "formula placeholders resolve to cell refs"


def test_render_logs_deliverable_event_without_content(tmp_path):
    change = _change_dir(tmp_path)
    render_workbook.render(change / "workbook.json", xlsx=False, host="claude-code")
    log = tmp_path / "logs" / "workflows.jsonl"
    event = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event"] == "deliverable_generated"
    assert event["deliverable_type"] == "workbook"
    assert event["host"] == "claude-code"
    assert event["grounded_pct"] == 75
    text = json.dumps(event)
    assert "show version" not in text and "chg-001" not in text and "IOS-XE" not in text


def test_every_reference_example_is_a_renderable_spec():
    refs = sorted((_PLUGIN / "skills" / "generate-workbook" / "references").glob("workbook-*.md"))
    assert len(refs) == 6
    for ref in refs:
        block = re.search(r"```json\n(.*?)\n```", ref.read_text(encoding="utf-8"), re.S).group(1)
        spec = render_workbook.normalise(json.loads(block))
        assert spec["sheets"], ref.name


def test_redacted_preview_drops_hosts_ips_and_secrets(tmp_path):
    spec = {"title": "Core upgrade", "summary_fields": {"Hostname": "chi-core-rtr-01", "Mgmt IP": "10.20.30.40"},
            "sheets": [{"name": "Steps", "headers": ["Device", "Command"], "rows": [
                {"device": "chi-core-rtr-01", "command": "ping 10.20.30.40 source Lo0"},
                {"device": "chi-core-rtr-02", "command": "snmp-server community S3cr3tRO RO"},
            ]}]}
    change = tmp_path / "documents" / "chg-9"
    change.mkdir(parents=True)
    (change / "workbook.json").write_text(json.dumps(spec), encoding="utf-8")
    render_workbook.render(change / "workbook.json", out_dir=change / "share", xlsx=False, redact=True)
    page = (change / "share" / "index.html").read_text(encoding="utf-8")
    for secret in ("chi-core-rtr-01", "chi-core-rtr-02", "10.20.30.40", "S3cr3tRO"):
        assert secret not in page, secret
    assert "HOST-1" in page and "IP-1" in page
    assert not (change / "share" / "workbook.xlsx").exists()
