#!/usr/bin/env python3
"""Post-write hook: validate generated automation and hand the findings to the model.

When the agent writes a playbook, Terraform file, Python script, Jinja template or
device config under a `configs/`, `automation/` or `playbooks/` directory, this runs
`damira validate` on it and returns the result as extra context. The model sees the
lint/syntax/audit failures on its next turn and can fix them itself. That loop is the
lift over a host model writing YAML unchecked (#471).

One handler, two hosts, selected with --host:
  claude-code  PostToolUse on Write|Edit|MultiEdit; path in tool_input.file_path;
               output {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                              "additionalContext": ...}}
  cursor       postToolUse (matcher on the write tools; cursor.com/docs/agent/hooks
               documents `Write`); path in tool_input; output {"additional_context": ...}.
               afterFileEdit can't return context to the agent, so it isn't used.

Runs validate in hook mode: the file is model-written, so Jinja is sandboxed, Ansible
checks an isolated copy, Terraform stops at fmt, and the run has a 60s budget (the hook
configs allow 90s).

Telemetry (#475): the host's session id groups saves of one file into a loop, and the
model plus token usage ride along on the event — from the Claude Code transcript (summed
per message, attributed as the delta since this session's previous validation) or the
Cursor payload's `model` (Cursor reports no tokens). Anything absent stays null.

Posture: an accuracy aid, not a gate. The write already happened, and a hook that errors
on every save gets uninstalled. Any failure here exits 0 quietly.
"""

import json
import os
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

WATCHED_DIRS = {"configs", "automation", "playbooks"}
WATCHED_EXTS = {".yml", ".yaml", ".tf", ".py", ".j2", ".jinja", ".jinja2", ".cfg", ".conf", ".txt"}
MAX_CONTEXT = 6000
# Tools that write files. Cursor documents `Write`; the rest are accepted in case a host
# reports an edit under another name. Anything else (Read, Grep, Shell) is ignored.
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "StrReplace"}


def _target(event: dict) -> "Path | None":
    tool_input = event.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            tool_input = {}
    raw = (tool_input.get("file_path") or tool_input.get("path") or tool_input.get("target_file")
           or event.get("file_path") or "")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        roots = event.get("workspace_roots") or []
        base = event.get("cwd") or (roots[0] if roots else "") or os.getcwd()
        path = Path(base) / path
    if path.suffix.lower() not in WATCHED_EXTS or not WATCHED_DIRS & set(path.parts[:-1]):
        return None
    if path.suffix.lower() == ".txt" and "configs" not in path.parts:
        return None
    return path if path.is_file() else None


def _transcript_usage(transcript: str) -> dict:
    """Model and cumulative usage for a Claude Code session, deduplicated by message id
    (one API message spans several transcript lines). Returns {} if unreadable."""
    per_message, model = {}, None
    try:
        with open(Path(transcript).expanduser(), "rb") as fh:
            for raw in fh:
                if b'"assistant"' not in raw or b'"usage"' not in raw:
                    continue
                try:
                    msg = json.loads(raw).get("message") or {}
                except ValueError:
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict) or msg.get("model") in (None, "<synthetic>"):
                    continue
                model = msg["model"]
                per_message[msg.get("id") or len(per_message)] = usage
    except OSError:
        return {}
    if not per_message:
        return {}
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for u in per_message.values():
        read, write = int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0)
        total["input"] += int(u.get("input_tokens") or 0) + read + write
        total["output"] += int(u.get("output_tokens") or 0)
        total["cache_read"] += read
        total["cache_write"] += write
    return {"model": model, **total}


def _usage_delta(session_id: str, totals: dict) -> dict:
    """Tokens since this session's previous validation, so summing a loop's events gives
    the loop's usage. State lives next to the salt, keyed by a salted session hash."""
    import events

    path = events._state_dir() / "telemetry_usage.json"
    key = events._hash(events._salt(), session_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    prev = state.get(key) or {}
    delta = {k: max(totals[k] - int(prev.get(k) or 0), 0) for k in ("input", "output", "cache_read", "cache_write")}
    state.pop(key, None)
    state[key] = {k: totals[k] for k in delta}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(list(state.items())[-50:])), encoding="utf-8")
    except OSError:
        pass
    return delta


def _telemetry(event: dict, host: str) -> dict:
    """validate.run kwargs for the loop and model fields. Never raises."""
    try:
        session = event.get("session_id") or event.get("conversation_id") or ""
        out = {"session_id": session if isinstance(session, str) else ""}
        if host == "cursor":
            if isinstance(event.get("model"), str):
                out["model"] = event["model"]
            return out
        transcript = event.get("transcript_path")
        usage = _transcript_usage(transcript) if isinstance(transcript, str) and transcript else {}
        if usage:
            delta = _usage_delta(out["session_id"] or transcript, usage)
            out.update(model=usage["model"], input_tokens=delta["input"], output_tokens=delta["output"],
                       cache_read=delta["cache_read"], cache_write=delta["cache_write"])
        return out
    except Exception:  # noqa: BLE001
        return {}


def _context(result: dict, path: Path) -> "str | None":
    import validate

    counts = result["counts"]
    if result["status"] == "empty":
        return None
    report = validate.format_human(result, base=path.parent)
    if result["status"] == "unverified":
        return (f"damira validate could NOT validate {path.name}: none of its checks could run on "
                "this machine, so the file is unchecked. Tell the user it was not validated and "
                "pass on the install hints below. Do not describe it as validated.\n\n" + report)
    if result["status"] == "pass" and not counts["warn"]:
        if not counts["skipped"]:
            return f"damira validate {path.name}: PASS ({counts['pass']} checks)."
        return (f"damira validate {path.name}: PASS on the checks that ran; {counts['skipped']} "
                "were skipped. Mention the skipped ones to the user.\n\n" + report)
    if result["status"] == "fail":
        lead = (f"damira validate found problems in {path.name}, which you just wrote. Fix every "
                "FAIL below and save again; the check re-runs on each save. If it still fails "
                "after 3 rounds, stop and tell the user what is left rather than looping. Do not "
                "tell the user this file is ready while any check fails.")
    else:
        lead = (f"damira validate passed {path.name} with warnings. Fix them if they are real "
                "issues, or tell the user why they are acceptable. Findings marked (whole config) "
                "only matter if this file is a complete device config, not a snippet.")
    text = f"{lead}\n\n{report}"
    return text if len(text) <= MAX_CONTEXT else text[:MAX_CONTEXT] + "\n…(truncated)"


def main() -> None:
    host = "cursor" if "--host=cursor" in sys.argv or sys.argv[-1] == "cursor" else "claude-code"
    event = json.loads(sys.stdin.read() or "{}")

    if event.get("tool_name", "Write") not in WRITE_TOOLS:
        sys.exit(0)

    path = _target(event)
    if path is None:
        sys.exit(0)

    import validate

    context = _context(validate.run(path, host=host, mode="hook", **_telemetry(event, host)), path)
    if not context:
        sys.exit(0)

    if host == "cursor":
        print(json.dumps({"additional_context": context}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": context}}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"Damira validate hook skipped ({type(exc).__name__}: {exc}).", file=sys.stderr)
        sys.exit(0)
