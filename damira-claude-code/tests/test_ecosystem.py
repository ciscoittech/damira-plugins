"""Ecosystem connectors (#480): record schemas, the init Ecosystem block, and MCP detection.

Identical in plugins/damira and plugins/damira-cursor.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "scripts"))

import ecosystem  # noqa: E402

VENDORS = ("ServiceNow", "Jira/JSM", "monday", "Freshservice")


def test_every_required_field_maps_for_each_vendor():
    for schema, fields in ecosystem.SCHEMAS.items():
        for vendor in VENDORS:
            mapping = ecosystem.MAPPINGS[schema][vendor]
            missing = [f for f in fields["required"] if not mapping.get(f)]
            assert not missing, f"{schema}/{vendor} lacks {missing}"
    required = set(ecosystem.SCHEMAS["change_request"]["required"])
    assert {"cmdb_ci", "risk", "implementation_plan", "backout_plan", "test_plan",
            "validate_report"} <= required
    # Freshservice v2 planning_fields: reason_for_change, change_impact, rollout_plan, backout_plan
    fresh = ecosystem.MAPPINGS["change_request"]["Freshservice"]
    assert fresh["implementation_plan"] == "planning_fields.rollout_plan"


def test_init_writes_an_ecosystem_block_and_rerun_replaces_it(tmp_path):
    def init(*args):
        subprocess.run([sys.executable, str(PLUGIN / "scripts" / "damira.py"), "init",
                        "--dir", str(tmp_path), "--target", "claude", *args],
                       capture_output=True, text=True, check=True)

    init("--ecosystem", "itsm=ServiceNow:NetOps", "--ecosystem", "chat=Slack:#noc",
         "--change-type", "normal")
    text = (tmp_path / "CLAUDE.md").read_text()
    block = text[text.index("## Ecosystem"):text.index("<!-- damira:end -->")]
    assert "~~itsm: ServiceNow" in block and "NetOps" in block and "~~chat: Slack" in block
    assert "normal" in block

    init("--ecosystem", "itsm=Jira Service Management:NET")
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.count("## Ecosystem") == 1 and text.count("<!-- damira:begin -->") == 1
    assert "Jira Service Management" in text and "ServiceNow" not in text

    # User input must not add markdown lines inside the managed block.
    block = ecosystem.render_block(["itsm=ServiceNow:NetOps\n## Injected"], "")
    assert "\n## Injected" not in block


def test_detection_classifies_servers_and_never_prints_secrets(tmp_path):
    secret = "sk-live-DO-NOT-PRINT-123"
    config = {"mcpServers": {
        "atlassian": {"url": f"https://mcp.atlassian.com/v1/sse?token={secret}",
                      "headers": {"Authorization": f"Bearer {secret}"}},
        "team-slack": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-slack"],
                       "env": {"SLACK_BOT_TOKEN": secret}},
        "weather": {"command": "weather-mcp", "env": {"API_KEY": secret}},
        # Atlassian's documented wrapper for clients without remote MCP: host is in an arg.
        "work": {"command": "npx", "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/sse"]},
        "helix-core": {"command": "p4-mcp"},
        "oncall": {"command": "npx", "args": ["@splunk/splunk-oncall-mcp"]},
    }}
    (tmp_path / ".mcp.json").write_text(json.dumps(config))
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(json.dumps(config))

    found = ecosystem.classify(ecosystem.load_mcp_servers([tmp_path / ".mcp.json"]))
    assert found["tracker"] == ["atlassian", "work"] and found["itsm"] == ["atlassian", "work"]
    assert found["chat"] == ["team-slack"]
    assert found["paging"] == ["oncall"] and "observability" not in found
    assert "weather" not in json.dumps(found) and "helix-core" not in json.dumps(found)

    # The host's session-start hook: Claude Code reads .mcp.json, Cursor reads .cursor/mcp.json.
    env = {**os.environ, "HOME": str(tmp_path), "DAMIRA_LOG_DIR": str(tmp_path / "log"),
           "CLAUDE_PROJECT_DIR": str(tmp_path)}
    out = subprocess.run([sys.executable, str(PLUGIN / "hooks-handlers" / "session_start.py")],
                         input=json.dumps({"workspace_roots": [str(tmp_path)]}), cwd=tmp_path,
                         env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    payload = json.loads(out.stdout)
    if PLUGIN.name == "damira-cursor":
        context = payload["additional_context"]
    else:  # Claude Code only reads additionalContext under hookSpecificOutput
        assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        context = payload["hookSpecificOutput"]["additionalContext"]
    assert "atlassian" in context and "team-slack" in context
    assert secret not in out.stdout + out.stderr
