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
the write when none does. "Grounded" is judged on the result's content, not on the
call having happened (#372): an error, a refusal, a "no authoritative source" answer,
or search results that are only search-engine homepages ground nothing.

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

# The agent's explicit "found nothing" answer (scripts/damira.py NO_AUTHORITATIVE_RESULTS).
_NO_RESULTS_MARKERS = (
    "No authoritative source found",
    "No further web results available",
)

_SEARCH_TOOLS = ("damira_search_vendor_docs", "damira_search_cve", "damira_search_release_notes")

# Hosts that are never evidence: search-engine chrome and generic how-to filler (#372).
_FILLER_HOSTS = (
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "search.brave.com",
    "wikihow.com", "baidu.com", "yandex.com", "yandex.ru", "ask.com", "search.google",
)

_URL_HOST = re.compile(r"https?://([^/\s)\]>\"']+)", re.IGNORECASE)

_MIN_RESULT_CHARS = 20

_ASK_REASON = (
    "No grounded Damira result found in this session, and this writes to documents/. "
    "The document template tool always succeeds, so having a scaffold does not mean the "
    "research succeeded. If a lookup failed, say so rather than filling the gaps — a "
    "fabricated MOP reads exactly like a verified one. Confirm only if the content is "
    "genuinely grounded or the user asked for a draft."
)


def _is_filler_host(host: str) -> bool:
    host = host.lower().split(":")[0]
    return any(host == h or host.endswith("." + h) for h in _FILLER_HOSTS)


def _result_text(content) -> str:
    """Flatten a tool_result's content (string or list of content blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return "" if content is None else str(content)


def _grounds(tool_name: str, text: str, is_error: bool) -> bool:
    """Does this result actually carry evidence, as opposed to a call that happened?"""
    if is_error:
        return False
    text = text.strip()
    if len(text) < _MIN_RESULT_CHARS:
        return False
    if any(m in text for m in _REFUSAL_MARKERS) and len(text) < 400:
        return False  # short and refusal-shaped; long research may quote the wording
    if any(m in text for m in _NO_RESULTS_MARKERS):
        return False
    if any(t in tool_name for t in _SEARCH_TOOLS):
        hosts = _URL_HOST.findall(text)
        if hosts and all(_is_filler_host(h) for h in hosts):
            return False  # only search-engine homepages: the #372 failure
    return True


def _evidence_tool(name: str) -> bool:
    return bool(name) and any(tool in name for tool in _EVIDENCE_TOOLS)


def _has_evidence(transcript_path: str) -> bool:
    """True if any Damira data call in the transcript returned grounding content.

    Reads Claude Code's JSONL: assistant entries carry tool_use blocks (id, name) and the
    following user entries carry tool_result blocks (tool_use_id, content, is_error).
    Also accepts flat {"type": "tool_result", "name": ..., "content": ...} lines. A tool
    call on its own is never evidence; only its result can be.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        raise FileNotFoundError(transcript_path or "<empty transcript path>")

    tool_names: dict[str, str] = {}
    parsed_any = False
    raw_lines: list[str] = []

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            raw_lines.append(line)
            try:
                entry = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(entry, dict):
                continue
            parsed_any = True

            # Flat form (older transcripts, tests)
            if entry.get("type") == "tool_result" and _evidence_tool(str(entry.get("name", ""))):
                if _grounds(entry["name"], _result_text(entry.get("content")), bool(entry.get("is_error"))):
                    return True
                continue

            message = entry.get("message")
            blocks = message.get("content") if isinstance(message, dict) else None
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("id"):
                    tool_names[block["id"]] = str(block.get("name", ""))
                elif block.get("type") == "tool_result":
                    name = tool_names.get(str(block.get("tool_use_id", "")), "")
                    if _evidence_tool(name) and _grounds(
                        name, _result_text(block.get("content")), bool(block.get("is_error"))
                    ):
                        return True

    if parsed_any:
        return False

    # Unparseable transcript format: fall back to the old line heuristic, but only on
    # result lines and never on an explicit "found nothing".
    for line in raw_lines:
        if not any(tool in line for tool in _EVIDENCE_TOOLS):
            continue
        if '"tool_result"' not in line and '"toolResult"' not in line:
            continue
        if any(m in line for m in _REFUSAL_MARKERS + _NO_RESULTS_MARKERS):
            continue
        return True
    return False


_WORKBOOK_SPEC = re.compile(r"(workbook|\.damira)\.json$", re.IGNORECASE)


def _workbook_grounding_note(path: str, tool_input: dict) -> None:
    """#484: a workbook spec is about to be written in a grounded session. Say which
    command cells the saved evidence doesn't back. A note, never a decision: the
    renderer tags them UNVERIFIED either way. Silent on anything it can't parse."""
    content = tool_input.get("content")
    if not _WORKBOOK_SPEC.search(path) or not isinstance(content, str):
        return
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
        import workbook_grounding

        spec = json.loads(content)
        evidence = os.path.join(os.path.dirname(path), "evidence")
        corpus = workbook_grounding.load_corpus(evidence)
        _, unverified, checked = workbook_grounding.ground_spec(spec, corpus)
    except Exception:  # noqa: BLE001
        return
    if not unverified:
        return
    note = "Damira workbook check: " + workbook_grounding.summary_line(unverified, checked, not corpus)
    print(json.dumps({
        "systemMessage": note,
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note},
    }))


def main() -> None:
    event = json.loads(sys.stdin.read())

    if event.get("tool_name") not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        sys.exit(0)

    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not isinstance(path, str) or not _GUARDED_PATH.search(path):
        sys.exit(0)

    if _has_evidence(event.get("transcript_path", "")):
        _workbook_grounding_note(path, tool_input)
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
