#!/usr/bin/env python3
"""Cursor device-execution gate: enforce advisor mode.

The Claude Code counterpart (plugins/damira/hooks-handlers/device_gate.py) rides on a
single PreToolUse event. Cursor splits the two paths it needs to cover across two
events, which is actually cleaner:

  beforeShellExecution — the terminal path. The sanctioned workflow reaches devices
    through the user's own SSH keys / VPN / jump hosts, so no credentials pass through
    Damira. `command` arrives at the TOP LEVEL of the payload, not under tool_input.

  beforeMCPExecution  — the lab-only ssh_command / network_device_command tools.
    `tool_name` identifies the call.

One handler serves both because Cursor gives them the same output contract:
`{"permission": "allow" | "deny" | "ask"}`, and exit 2 also blocks.

FAIL CLOSED. Cursor, like Claude Code, treats exit codes other than 2 as fail-open —
the action proceeds. So an unhandled exception here would let SSH through while the
user believed advisor mode held. Every failure path emits a deny, and the only allow
is a positive determination that the call is safe.

Mode is read from DAMIRA_EXECUTION_MODE, which mcp.json sets for the MCP server. Cursor
has no userConfig equivalent, so the env var is the single source for the mode.

Shell matching is best-effort; obfuscation can defeat it. A floor, not a proof.
"""

import json
import os
import re
import sys

_DEVICE_CMD = re.compile(
    r"(?:^|[\s;&|(`$])(?:ssh|telnet|nc|ncat|netcat|sshpass)(?:\s|$)"
)

_BLOCKED_MCP_TOOLS = {
    "ssh_command",
    "network_device_command",
    # Cursor may namespace MCP tools; match both bare and prefixed forms.
    "mcp__damira__ssh_command",
    "mcp__damira__network_device_command",
}

_ELEVATED = {"guided", "lab"}

_ASK_MSG = (
    "Damira is in advisor mode: it recommends commands and never runs them on network "
    "devices itself. This is your own shell, so it's your call — approve it if this host "
    "isn't network gear. Damira's own device tools stay blocked either way."
)

_DENY_MSG = (
    "Damira is in advisor mode and does not run commands on network devices. Give the "
    "engineer the exact commands to run and take their pasted output. To let Damira run "
    "read-only show commands, the user must set DAMIRA_EXECUTION_MODE to guided or lab."
)


def _deny() -> None:
    print(json.dumps({"permission": "deny", "agent_message": _DENY_MSG, "user_message": _DENY_MSG}))
    sys.exit(0)


def _allow() -> None:
    print(json.dumps({"permission": "allow"}))
    sys.exit(0)


def _ask() -> None:
    """Hand a shell ssh/telnet/nc to the user instead of blocking it.

    Engineers reach servers, jump hosts and their own VPS the same way they reach
    network gear, so a blanket block broke ordinary terminal work the moment the
    plugin was installed. The guarantee that matters — the agent never reaches a
    device on its own — still holds, because the user decides. Damira's own device
    tools stay denied, and DAMIRA_DEVICE_GATE=strict restores the hard block.
    """
    print(json.dumps({"permission": "ask", "agent_message": _ASK_MSG, "user_message": _ASK_MSG}))
    sys.exit(0)


def main() -> None:
    event = json.loads(sys.stdin.read())
    elevated = os.environ.get("DAMIRA_EXECUTION_MODE", "advisor").strip().lower() in _ELEVATED

    # beforeMCPExecution — identified by tool_name.
    tool_name = event.get("tool_name")
    if tool_name:
        if tool_name in _BLOCKED_MCP_TOOLS and not elevated:
            _deny()
        _allow()

    # beforeShellExecution — command at top level.
    command = event.get("command", "")
    if isinstance(command, str) and _DEVICE_CMD.search(command) and not elevated:
        if os.environ.get("DAMIRA_DEVICE_GATE", "ask").strip().lower() == "strict":
            _deny()
        _ask()

    _allow()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — fail closed on ANY unexpected failure
        # Deny via BOTH channels: JSON permission and exit 2, so a swallowed stdout
        # still blocks.
        print(json.dumps({
            "permission": "deny",
            "agent_message": f"Damira device gate failed and blocked the call "
                             f"({type(exc).__name__}). This is deliberate: it fails closed.",
        }))
        sys.exit(2)
