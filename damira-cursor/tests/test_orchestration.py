"""#474: Damira orchestrates the engineer's NetBox/AAP/pyATS/Terraform MCP servers.

Detection, the init capability block, the advisor-mode gate on those servers, and the
source-of-truth-change skill. Identical in plugins/damira and plugins/damira-cursor.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent
SIBLING = PLUGIN.parent / ("damira-cursor" if PLUGIN.name == "damira" else "damira")
CURSOR = PLUGIN.name == "damira-cursor"
sys.path.insert(0, str(PLUGIN / "scripts"))

import ecosystem  # noqa: E402

SECRET = "tok-DO-NOT-PRINT-474"
SERVERS = {
    "netbox": {"command": "uvx", "args": ["netbox-mcp-server"], "env": {"NETBOX_TOKEN": SECRET}},
    "aap": {"url": "https://aap.lab.example/mcp", "headers": {"Authorization": f"Bearer {SECRET}"}},
    "pyats-lab": {"command": "npx", "args": ["-y", "pyats-mcp-server"]},
    "terraform": {"command": "docker", "args": ["run", "-i", "hashicorp/terraform-mcp-server"]},
    "team-slack": {"command": "npx", "args": ["@modelcontextprotocol/server-slack"]},
}


def test_detection_classifies_orchestration_servers_across_host_configs(tmp_path):
    root, home = tmp_path / "ws", tmp_path / "home"
    (root / ".cursor").mkdir(parents=True)
    (home / ".cursor").mkdir(parents=True)
    (root / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {
        k: SERVERS[k] for k in ("netbox", "aap")}}))
    (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {
        k: SERVERS[k] for k in ("pyats-lab", "terraform")}}))
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "nautobot": {"command": "nautobot-mcp"}, "team-slack": SERVERS["team-slack"]}}))

    found = ecosystem.classify(ecosystem.load_workspace_servers(root, home=home))
    assert sorted(found["source-of-truth"]) == ["nautobot", "netbox"]
    assert found["automation"] == ["aap"]
    assert found["testing"] == ["pyats-lab"]
    assert found["iac"] == ["terraform"]
    assert found["chat"] == ["team-slack"]


def test_init_writes_capability_block_from_detected_servers(tmp_path):
    ws, home = tmp_path / "ws", tmp_path / "home"
    ws.mkdir()
    home.mkdir()
    (ws / ".mcp.json").write_text(json.dumps({"mcpServers": SERVERS}))
    env = {**os.environ, "HOME": str(home)}

    def init(*extra):
        return subprocess.run([sys.executable, str(PLUGIN / "scripts" / "damira.py"), "init",
                               "--dir", str(ws), *extra], env=env, capture_output=True,
                              text=True, check=True)

    out = init()
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (ws / name).read_text()
        block = text[text.index("## Automation capabilities"):text.index("<!-- damira:end -->")]
        for server in ("netbox", "aap", "pyats-lab", "terraform"):
            assert server in block, (name, server)
        assert "~~automation" in block and "check mode" in block
        assert "team-slack" not in block
        assert SECRET not in text and "aap.lab.example" not in text
    assert SECRET not in out.stdout + out.stderr

    init("--no-detect")
    assert "## Automation capabilities" not in (ws / "CLAUDE.md").read_text()


def _gate(server: str, tool: str, args: dict, mode: str = "advisor", gate: str = "") -> str:
    """Run the host's device gate on one MCP call; return allow / ask / deny."""
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_OPTION_EXECUTION_MODE": mode,
           "DAMIRA_EXECUTION_MODE": mode}
    if gate:
        env["CLAUDE_PLUGIN_OPTION_DEVICE_GATE"] = env["DAMIRA_DEVICE_GATE"] = gate
    if CURSOR:  # beforeMCPExecution: bare tool name, JSON-string input, server url/command
        spec = SERVERS.get(server, {"command": server})
        payload = {"hook_event_name": "beforeMCPExecution", "tool_name": tool,
                   "tool_input": json.dumps(args)}
        payload.update({"url": spec["url"]} if "url" in spec
                       else {"command": " ".join([spec["command"], *spec.get("args", [])])})
    else:
        payload = {"tool_name": f"mcp__{server}__{tool}", "tool_input": args}
    proc = subprocess.run([sys.executable, str(PLUGIN / "hooks-handlers" / "device_gate.py")],
                          input=json.dumps(payload), capture_output=True, text=True, env=env)
    if CURSOR:
        return "deny" if proc.returncode == 2 else json.loads(proc.stdout)["permission"]
    if proc.returncode == 2:
        return "deny"
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return "allow"  # untouched: the host's own permission rules apply
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


GATE_CASES = [
    # Every launch asks: AAP ignores job_type=check unless the template prompts for it.
    ("aap", "launch_job_template", {"id": 7, "job_type": "check"}, "advisor", "", "ask"),
    ("aap", "launch_job_template", {"id": 7, "job_type": "check"}, "advisor", "strict", "ask"),
    ("aap", "launch_job_template", {"id": 7, "extra_data": {"job_type": "run"}}, "advisor", "", "ask"),
    ("aap", "launch_job_template", {"id": 7}, "advisor", "strict", "deny"),
    # extra_vars is a playbook variable, not the launch job type: this is a live run.
    ("aap", "launch_job_template", {"id": 12, "extra_vars": {"job_type": "check"}},
     "advisor", "strict", "deny"),
    ("aap", "launch_workflow_job_template", {"id": 3, "extra_vars": {"job_type": "check"}},
     "advisor", "strict", "deny"),
    ("AAP", "launch_job_template", {"id": 7}, "advisor", "strict", "deny"),
    ("aap", "list_job_templates", {}, "advisor", "", "allow"),
    ("pyats-lab", "pyats_configure_device", {"device": "r1", "config": "no ip routing"},
     "advisor", "", "deny"),
    ("pyats-lab", "pyats_run_show_command", {"device": "r1", "command": "show version"},
     "advisor", "", "ask"),
    ("terraform", "create_run", {"workspace": "core"}, "advisor", "", "deny"),
    ("terraform", "search_providers", {"query": "netbox"}, "advisor", "", "allow"),
    ("terraform", "get_run_details", {"run_id": "run-1"}, "advisor", "", "allow"),
    ("netbox", "netbox_get_objects", {"object_type": "devices"}, "advisor", "", "allow"),
    ("team-slack", "slack_post_message", {"text": "apply terraform"}, "advisor", "", "allow"),
    ("pyats-lab", "pyats_configure_device", {"device": "r1"}, "lab", "", "ask"),
]


def test_gate_on_orchestration_mcp_calls():
    got = [(case[:2], _gate(*case[:5])) for case in GATE_CASES]
    assert got == [(case[:2], case[5]) for case in GATE_CASES]
    decision, reason = ecosystem.gate_mcp("mcp__aap__launch_job_template",
                                          {"id": 7, "job_type": "check"})
    assert decision == "ask" and "prompt" in reason.lower()
    nested = ecosystem.gate_mcp("mcp__aap__launch_job_template",
                                {"id": 7, "extra_vars": {"job_type": "check"}})
    assert nested[0] == "ask" and "not in check mode" in nested[1]


def test_hooks_register_the_orchestration_gate():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
    if CURSOR:
        mcp = hooks["beforeMCPExecution"]
        assert any("device_gate.py" in h["command"] and h.get("failClosed") for h in mcp)
        return
    matcher = next(h["matcher"] for h in hooks["PreToolUse"]
                   if "device_gate.py" in h["hooks"][0]["command"])
    for category in ("automation", "testing", "iac"):
        for fp in ecosystem.CATEGORIES[category]:
            assert re.fullmatch(matcher, f"mcp__{fp}__launch"), fp
    for name in ("mcp__AAP__launch_job_template", "mcp__Terraform__create_run",
                 "mcp__PyATS-Lab__pyats_configure_device"):
        assert re.fullmatch(matcher, name), name  # server names are not always lowercase
    assert re.fullmatch(matcher, "mcp__damira__ssh_command")
    assert not re.fullmatch(matcher, "mcp__team-slack__slack_post_message")


SKILL = "source-of-truth-change"
TOOL_NAMES = re.compile(r"mcp__|netbox_get_objects|launch_job_template|job_templates_launch|"
                        r"pyats_\w+|search_providers|create_run|action_run")


def test_source_of_truth_change_skill_ships_in_both_plugins():
    skill = PLUGIN / "skills" / SKILL
    text = (skill / "SKILL.md").read_text()
    assert len(text.splitlines()) <= 130
    for placeholder in ("~~source-of-truth", "~~automation", "~~testing", "~~iac"):
        assert placeholder in text, placeholder
    assert f"--skill {SKILL}" in text and "damira-fixer" in text
    refs = {p.name: p.read_bytes() for p in sorted((skill / "references").glob("*.md"))}
    assert set(refs) == {"netbox-intent.md", "handoff-aap.md", "handoff-pyats.md",
                         "handoff-terraform.md"}
    for name, body in [("SKILL.md", text.encode()), *refs.items()]:
        hit = TOOL_NAMES.search(body.decode())
        assert not hit, f"{name}: concrete tool name {hit.group(0)!r}"
    if SIBLING.is_dir():
        theirs = {p.name: p.read_bytes()
                  for p in sorted((SIBLING / "skills" / SKILL / "references").glob("*.md"))}
        assert refs == theirs, "references must be byte-identical across plugins"
        for f in ("scripts/ecosystem.py", "tests/test_orchestration.py"):
            assert (PLUGIN / f).read_bytes() == (SIBLING / f).read_bytes(), f
