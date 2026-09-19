"""Regression tests for the plugin's two enforcement hooks.

These are the two eval cases from the plan, written as runnable tests. `claude plugin
eval` is gated behind early access on this account and its case schema is not publicly
documented, so authoring case.yaml files would mean guessing at a format. These assert
the same guarantees and run today; port them when eval access opens.

Case 1 — the fabricated-MOP regression. On 2026-07-23 a tier-gate refusal came back as
a successful tool result, was read as research, and became a confident 371-line IOS-XE
upgrade MOP that reported itself as verified.

Case 2 — the false positive. A gate that fires on legitimate content gets uninstalled,
which protects nothing. Real research may quote refusal wording verbatim.

The device gate's fail-closed behaviour is tested hardest, because Claude Code treats
every exit code except 2 as non-blocking — including 1, which is what an unhandled
Python traceback returns. A crash that fails open would leave the user believing
advisor mode was enforced when it was not.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HANDLERS = Path(__file__).resolve().parent.parent / "hooks-handlers"
DEVICE_GATE = HANDLERS / "device_gate.py"
DOCUMENT_GATE = HANDLERS / "document_gate.py"

BLOCK = 2
ALLOW = 0


def run_hook(script: Path, payload, mode: str = "advisor", gate: str = ""):
    """Run a hook handler the way Claude Code does: JSON on stdin, exit code out."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    env = {"CLAUDE_PLUGIN_OPTION_EXECUTION_MODE": mode, "PATH": "/usr/bin:/bin"}
    if gate:
        env["CLAUDE_PLUGIN_OPTION_DEVICE_GATE"] = gate
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


# --- device gate -----------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'ssh rtr1 "show ip bgp summary"',
        "echo config | ssh rtr1",
        "telnet 10.0.0.1",
        "sshpass -p x ssh admin@10.0.0.1",
        "nc 10.0.0.1 23",
        "ssh -J jump admin@10.0.0.1",
    ],
)
def test_device_gate_asks_before_shell_device_access(command):
    """The sanctioned workflow reaches devices via the terminal, so Bash must be gated.

    It asks rather than blocks: an engineer's shell ssh is as likely to be a server
    or jump host as network gear, and a blanket block broke ordinary terminal work
    the moment the plugin was installed. The agent still can't reach a device on its
    own — the user decides.
    """
    code, out, _ = run_hook(DEVICE_GATE, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert code == ALLOW, f"must not hard-block the user's own shell: {command}"
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "ask", command
    assert "advisor mode" in decision["permissionDecisionReason"].lower()


@pytest.mark.parametrize("command", ["ssh admin@10.0.0.1", "telnet 10.0.0.1"])
def test_strict_mode_restores_the_hard_block(command):
    code, _, err = run_hook(DEVICE_GATE, {"tool_name": "Bash", "tool_input": {"command": command}},
                            gate="strict")
    assert code == BLOCK
    assert "advisor mode" in err.lower()


@pytest.mark.parametrize(
    "tool",
    [
        "mcp__damira__ssh_command",
        "mcp__damira__network_device_command",
        # how Claude Code names them when the server ships inside the plugin
        "mcp__plugin_damira_damira__ssh_command",
        "mcp__plugin_damira_damira__network_device_command",
    ],
)
def test_device_gate_blocks_mcp_tools_in_advisor(tool):
    """Damira's own device tools are never merely asked about: the product claim is
    that the agent cannot drive a device itself."""
    code, _, _ = run_hook(DEVICE_GATE, {"tool_name": tool, "tool_input": {"host": "10.0.0.1"}})
    assert code == BLOCK


@pytest.mark.parametrize(
    "command",
    [
        "grep Port /etc/ssh/sshd_config",  # word boundary: reading config is not access
        "cat notes-about-ssh.md",
        "ls -la",
        "python3 -m pytest",
    ],
)
def test_device_gate_allows_non_device_commands(command):
    """False positives here block ordinary work, so the boundary matters."""
    code, _, _ = run_hook(DEVICE_GATE, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert code == ALLOW, f"should not be treated as device access: {command}"


@pytest.mark.parametrize("mode", ["guided", "lab"])
def test_device_gate_allows_when_user_elevated_mode(mode):
    code, _, _ = run_hook(
        DEVICE_GATE, {"tool_name": "Bash", "tool_input": {"command": "ssh rtr1 'show ver'"}}, mode=mode
    )
    assert code == ALLOW


@pytest.mark.parametrize(
    "payload",
    ["not json at all", "", "{}", '{"tool_name": null}', '{"tool_name":"Bash","tool_input":null}'],
)
def test_device_gate_fails_closed_on_malformed_input(payload):
    """Exit 1 is NON-blocking in Claude Code, and a traceback exits 1.

    So every failure path must exit 2. Anything else silently permits the call while
    the user believes the gate is holding.
    """
    code, _, _ = run_hook(DEVICE_GATE, payload)
    assert code in (ALLOW, BLOCK), "must be a decision, never a crash code"
    if payload in ("not json at all", ""):
        assert code == BLOCK, "unparseable input must fail closed"


def test_device_gate_never_exits_one():
    """Exit 1 would be read as a non-blocking error and let the call through."""
    for payload in ["garbage", "", "{}", '{"tool_name":"Bash"}']:
        code, _, _ = run_hook(DEVICE_GATE, payload)
        assert code != 1, f"exit 1 is non-blocking — payload {payload!r} would permit the call"


# --- document gate ---------------------------------------------------------------


def _transcript(tmp_path: Path, *lines: str) -> str:
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(lines) + ("\n" if lines else ""))
    return str(p)


def _decision(stdout: str):
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] if stdout.strip() else None


REFUSAL_LINE = json.dumps(
    {
        "type": "tool_result",
        "name": "mcp__damira__damira_upgrade_plan",
        "content": "Model meta-llama/llama-3.3-70b-instruct is not available on your current plan.",
    }
)

GROUNDED_LINE = json.dumps(
    {
        "type": "tool_result",
        "name": "mcp__damira__damira_search_cve",
        "content": "CVE-2023-20198 affects the IOS-XE web UI. Fixed in 17.9.4a.",
    }
)


def test_case1_refusal_only_transcript_stops_the_mop(tmp_path):
    """THE regression: the exact 2026-07-23 shape.

    The only Damira call in the session was a refusal. Writing a MOP from that is what
    produced a fabricated document that read as verified.
    """
    code, out, _ = run_hook(
        DOCUMENT_GATE,
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "documents/ios-xe-upgrade-mop.md"},
            "transcript_path": _transcript(tmp_path, REFUSAL_LINE),
        },
    )
    assert code == ALLOW
    assert _decision(out) == "ask", "a MOP built on a refusal must not be written silently"


def test_case1_grounded_transcript_allows_the_mop(tmp_path):
    """The gate must be invisible when the research actually happened."""
    code, out, _ = run_hook(
        DOCUMENT_GATE,
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "documents/ios-xe-upgrade-mop.md"},
            "transcript_path": _transcript(tmp_path, GROUNDED_LINE),
        },
    )
    assert code == ALLOW
    assert _decision(out) is None, "grounded work must not be interrupted"


def test_case2_false_positive_research_quoting_refusal_wording(tmp_path):
    """Case 2: legitimate research may quote gate wording verbatim.

    A grounded CVE result that happens to discuss the phrase must still count as
    evidence — otherwise the gate fires on real work and gets turned off.
    """
    quoting = json.dumps(
        {
            "type": "tool_result",
            "name": "mcp__damira__damira_search_cve",
            "content": "Advisory notes users saw 'rate limit exceeded' banners after upgrade.",
        }
    )
    code, out, _ = run_hook(
        DOCUMENT_GATE,
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "documents/advisory.md"},
            "transcript_path": _transcript(tmp_path, quoting),
        },
    )
    assert _decision(out) is None, "legitimate research must not be flagged"


def test_document_gate_ignores_non_document_writes(tmp_path):
    code, out, _ = run_hook(
        DOCUMENT_GATE,
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "src/app.py"},
            "transcript_path": _transcript(tmp_path),
        },
    )
    assert code == ALLOW and _decision(out) is None


def test_document_gate_defers_when_transcript_unreadable():
    """Accuracy control, not a security control — it must not block on its own failure."""
    code, out, _ = run_hook(
        DOCUMENT_GATE,
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "documents/mop.md"},
            "transcript_path": "/nonexistent/transcript.jsonl",
        },
    )
    assert code == ALLOW and _decision(out) is None


def test_document_gate_template_alone_is_not_evidence(tmp_path):
    """damira_document_template is local and always succeeds.

    Treating it as evidence would defeat the gate entirely, since a scaffold is always
    obtainable regardless of whether any research worked.
    """
    template_only = json.dumps(
        {
            "type": "tool_result",
            "name": "mcp__damira__damira_document_template",
            "content": "# Method of Procedure (MOP) — Required Sections ...",
        }
    )
    code, out, _ = run_hook(
        DOCUMENT_GATE,
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "documents/mop.md"},
            "transcript_path": _transcript(tmp_path, template_only),
        },
    )
    assert _decision(out) == "ask", "a template is a scaffold, not grounding"


def test_hook_matcher_routes_plugin_named_device_tools_to_the_gate():
    """The gate can only block what the PreToolUse matcher sends it."""
    import re
    hooks = json.loads((HANDLERS.parent / "hooks" / "hooks.json").read_text())
    matchers = [h["matcher"] for h in hooks["hooks"]["PreToolUse"]
                if "device_gate" in h["hooks"][0]["command"]]
    for tool in ("mcp__plugin_damira_damira__ssh_command", "mcp__damira__network_device_command"):
        assert any(re.fullmatch(m, tool) for m in matchers), tool
