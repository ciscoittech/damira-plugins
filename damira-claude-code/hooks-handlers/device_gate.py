#!/usr/bin/env python3
"""PreToolUse gate: block device execution unless the user opted out of advisor mode.

Advisor mode is Damira's default and its core safety claim: Damira recommends
commands, the engineer runs them. This hook is what makes that structural rather
than advisory, so it has to hold even when the model has been told otherwise by a
skill, by the user, or by text arriving inside tool output.

It covers two paths, because covering only the first leaves the sanctioned one open:

  1. The MCP tools `ssh_command` / `network_device_command`.
  2. `Bash` invoking ssh/telnet/nc — which is how the documented workflow reaches a
     device (the user's own keys, VPN, and jump hosts, so no credentials pass
     through Damira). A gate that only matched the MCP tool names would block the
     path nobody uses and miss the one everybody uses.

FAIL CLOSED. Claude Code treats every exit code except 2 as non-blocking, including
1 — so an unhandled Python traceback would let SSH through while the user still
believes advisor mode is enforced. Every failure path here therefore exits 2.

Damira's own device tools are denied outright in advisor mode. A shell ssh/telnet/nc
is instead handed to the user to approve, because that is their terminal and not
every host is network gear — a blanket block broke ordinary server work as soon as
the plugin was installed. Set device_gate to "strict" to block those too.

It also gates the engineer's own orchestration MCP servers (#474): Ansible AAP, pyATS
and Terraform. Every AAP job launch asks,
because AAP ignores job_type=check unless the template prompts for it. A pyATS config push or a Terraform run/apply is denied in advisor mode. The rules
live in scripts/ecosystem.py, shared with the Cursor plugin. The hooks.json matcher sees
only the tool name, so the server name must carry the product (aap, pyats, terraform...).

Shell matching is best-effort by nature; obfuscation can defeat it. It is a floor,
not a proof.
"""

import json
import os
import re
import sys
from pathlib import Path

# Word-boundary matched so "sshd_config" or "netcat-notes.md" don't trip the gate,
# while `ssh`, `ssh -J`, and `... | ssh host` all do.
_DEVICE_CMD = re.compile(
    r"(?:^|[\s;&|(`$])(?:ssh|telnet|nc|ncat|netcat|sshpass)(?:\s|$)"
)

# Matched on the tool part so every registration of a Damira server is covered:
# mcp__damira__* when added by hand, mcp__plugin_damira_damira__* when installed
# as a plugin. Exact names missed the plugin form.
_BLOCKED_MCP_SUFFIXES = ("__ssh_command", "__network_device_command")


def _is_blocked_mcp_tool(tool_name: str) -> bool:
    return (tool_name.startswith("mcp__") and "damira" in tool_name
            and tool_name.endswith(_BLOCKED_MCP_SUFFIXES))

_ELEVATED_MODES = {"guided", "lab"}

_DENY_REASON = (
    "Blocked: Damira is in advisor mode, which does not run commands on network "
    "devices. Give the engineer the exact commands to run and ask them to paste the "
    "output back. To let Damira run read-only show commands itself, the user must set "
    "the plugin's execution mode to guided or lab — you cannot elevate it yourself."
)


_ASK_REASON = (
    "Damira is in advisor mode: it recommends commands and never runs them on network "
    "devices itself. This is your own shell, so it's your call — approve it if this "
    "host isn't network gear. Damira's own device tools stay blocked either way."
)


def _deny(reason: str) -> None:
    print(reason, file=sys.stderr)
    sys.exit(2)


def _ask(reason: str) -> None:
    """Hand the decision to the user instead of blocking outright.

    A shell `ssh` is not necessarily a network device: engineers reach servers,
    jump hosts and their own VPS the same way, and a hard block made the plugin
    break their terminal the moment it was installed. Asking keeps the agent from
    reaching a device on its own — which is the actual guarantee — while leaving
    the engineer in charge of their own shell. Damira's device tools still fail
    closed, and DEVICE_GATE=strict restores the hard block here too.
    """
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> None:
    raw = sys.stdin.read()
    event = json.loads(raw)

    # Read the mode from the environment rather than the event: userConfig values are
    # exported as CLAUDE_PLUGIN_OPTION_*, and shell-form hook commands cannot take
    # ${user_config.*} substitution.

    mode = os.environ.get("CLAUDE_PLUGIN_OPTION_EXECUTION_MODE", "advisor").strip().lower()
    elevated = mode in _ELEVATED_MODES

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}

    if _is_blocked_mcp_tool(tool_name):
        if elevated:
            sys.exit(0)
        _deny(_DENY_REASON)

    strict = os.environ.get("CLAUDE_PLUGIN_OPTION_DEVICE_GATE", "ask").strip().lower() == "strict"
    if tool_name.startswith("mcp__"):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import ecosystem

        verdict = ecosystem.gate_mcp(tool_name, tool_input, mode=mode, strict=strict)
        if verdict and verdict[0] == "deny":
            _deny(verdict[1])
        if verdict and verdict[0] == "ask":
            _ask(verdict[1])
        sys.exit(0)

    if tool_name in ("Bash", "BashOutput"):
        command = tool_input.get("command", "")
        if isinstance(command, str) and _DEVICE_CMD.search(command):
            if elevated:
                sys.exit(0)
            if strict:
                _deny(_DENY_REASON)
            _ask(_ASK_REASON)

    # Not a device-execution call.
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — fail closed on ANY unexpected failure
        print(
            f"Damira device gate could not evaluate this call and blocked it "
            f"({type(exc).__name__}: {exc}). This is deliberate: the gate fails closed.",
            file=sys.stderr,
        )
        sys.exit(2)
