#!/usr/bin/env python3
"""PreToolUse gate: don't let an operational document get written without evidence.

On 2026-07-23 a tier-gate refusal came back from the API as a normal successful
result. The model read it as research and wrote a confident 371-line IOS-XE upgrade
MOP — fabricated CVEs, bug IDs, install commands, rollback triggers — then reported
that the tools had succeeded. Nothing in the flow objected.

The damage was not reading a bad string; it was writing a document an engineer would
execute against production. `damira_document_template` is local and always succeeds,
so a scaffold is obtainable whether or not any research worked. That makes the write
the real choke point.

So this checks the opposite of a denylist: rather than hunting for known-bad strings,
it asks whether any grounded Damira result exists in this session at all, and pauses
the write when none does.

Posture differs from device_gate.py on purpose. That one is a security control and
fails closed. This is an accuracy control: a gate that blocks legitimate writes gets
uninstalled, so uncertainty escalates to the user with "ask" and an unreadable
transcript defers rather than blocking.
"""

import json
import os
import re
import sys

# Documents an engineer acts on. Notes and scratch files are none of our business.
_GUARDED_PATH = re.compile(r"(^|/)documents/", re.IGNORECASE)

# Tools that return retrieved or diagnosed data. damira_document_template is
# deliberately absent — it is local, always succeeds, and grounds nothing.
_EVIDENCE_TOOLS = (
    "damira_search_vendor_docs",
    "damira_search_cve",
    "damira_search_release_notes",
    "damira_troubleshoot",
    "damira_upgrade_plan",
    "analyze_config",
    "damira_agent",
)

# If one of these appears in the same entry, that call was a refusal, not evidence.
_REFUSAL_MARKERS = (
    "is not available on your current plan",
    "You've used your monthly token budget",
    "Invalid API key",
    "Rate limit exceeded",
    "Demo limit reached",
    "require Enterprise subscription",
)

_ASK_REASON = (
    "No grounded Damira result found in this session, and this writes to documents/. "
    "The document template tool always succeeds, so having a scaffold does not mean the "
    "research succeeded. If a lookup failed, say so rather than filling the gaps — a "
    "fabricated MOP reads exactly like a verified one. Confirm only if the content is "
    "genuinely grounded or the user asked for a draft."
)


def _has_evidence(transcript_path: str) -> bool:
    """True if any successful Damira data call appears in the transcript.

    Line-oriented and string-based rather than schema-aware: the transcript format is
    not a stable contract, and a heuristic that degrades gracefully beats a parser that
    breaks silently on the next format change.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        raise FileNotFoundError(transcript_path or "<empty transcript path>")

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not any(tool in line for tool in _EVIDENCE_TOOLS):
                continue
            if any(marker in line for marker in _REFUSAL_MARKERS):
                continue  # that call was a refusal
            # A tool name with no refusal alongside it — treat as a real result.
            if '"tool_result"' in line or '"toolResult"' in line or '"content"' in line:
                return True
    return False


def main() -> None:
    event = json.loads(sys.stdin.read())

    if event.get("tool_name") not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        sys.exit(0)

    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not isinstance(path, str) or not _GUARDED_PATH.search(path):
        sys.exit(0)

    if _has_evidence(event.get("transcript_path", "")):
        sys.exit(0)

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": _ASK_REASON,
                }
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        # Defer rather than block: this is an accuracy gate, and a false block on every
        # write would get the plugin turned off, which protects nothing.
        print(
            f"Damira document gate skipped ({type(exc).__name__}: {exc}).",
            file=sys.stderr,
        )
        sys.exit(0)
