#!/usr/bin/env python3
"""SessionStart: tell the user which key and which execution mode they're on.

Two things are worth knowing before work starts rather than 40 seconds into an
incident: whether a real key is configured, and whether Damira may touch devices.

Deliberately does NOT call the API. A reachability probe would add latency to every
session start and would hard-fail on a transient blip — and the health endpoint has
a history of reporting healthy while the agent path is broken, so a green check here
would be worse than no check. Real failures surface as tool errors at the point of
use, which is now accurate since the MCP server marks them properly.

Never prints the key. Hook stdout becomes model context and flows on to tracing.
"""

import json
import os
import sys
from pathlib import Path


def _has_fallback_key() -> bool:
    """Same fallbacks the client uses when the plugin setting is blank (#452)."""
    if os.environ.get("DAMIRA_API_KEY", "").strip():
        return True
    config = Path.home() / ".damira" / "config"
    try:
        return config.is_file() and bool(config.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _ecosystem_note() -> str:
    """Connected ITSM/chat/paging/... servers (#480). Names only; best-effort, never raises."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import ecosystem

        project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        servers = ecosystem.load_mcp_servers([Path(project) / ".mcp.json"])
        servers += ecosystem.load_mcp_servers([Path.home() / ".claude.json"], project=project)
        detected = ecosystem.describe(ecosystem.classify(servers))
    except Exception:  # noqa: BLE001
        detected = ""
    lead = f"Ecosystem connectors configured here: {detected}. " if detected else ""
    return (
        lead + "claude.ai connectors can appear under UUID tool names, so find the engineer's "
        "~~itsm, ~~tracker, ~~chat and other ecosystem tools with tool search; the Ecosystem "
        "section of CLAUDE.md is the fallback. Damira drafts records; write them with the "
        "engineer's connector only after they confirm."
    )


def main() -> None:
    key = os.environ.get("CLAUDE_PLUGIN_OPTION_API_KEY", "").strip() or _has_fallback_key()
    mode = os.environ.get("CLAUDE_PLUGIN_OPTION_EXECUTION_MODE", "advisor").strip().lower()

    notes = []

    if not key:
        notes.append(
            "Damira has no API key configured and is running on the shared demo key "
            "(50 queries/day, rate limited). Tell the user they can add their own key "
            "in the plugin settings if they hit the limit — get one at "
            "damiraai.com/dashboard/api-keys."
        )

    if mode in ("guided", "lab"):
        notes.append(
            f"Damira execution mode is '{mode}': you may run read-only show commands on "
            "devices after asking. Never run configuration changes, clear commands, or "
            "reloads regardless of mode."
        )
    else:
        notes.append(
            "Damira is in advisor mode (default): recommend commands for the engineer to "
            "run and take their pasted output. Do not SSH to devices, and do not use the "
            "terminal to reach them — this is enforced and the attempt will be blocked."
        )

    notes.append(_ecosystem_note())

    if notes:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": " ".join(notes)}}))

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        # Informational only — never let it interfere with starting a session.
        print(f"Damira session hook skipped ({type(exc).__name__}).", file=sys.stderr)
        sys.exit(0)
