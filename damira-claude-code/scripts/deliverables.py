#!/usr/bin/env python3
"""Server deliverables (#484 T1): stop dropping them on the floor.

The agent returns files (a WorkbookSpec `.damira.json`, a runbook, a MOP) alongside the
answer. chat-sync passes the agent JSON through unchanged, so they arrive as top-level
`deliverables: [{filename, content, type}]` and/or as `messages[]` entries with
`role: "deliverable"`. call() used to return only `response`.

Where they go:
  - the workspace has a documents/ folder (set up by `damira init`) → documents/<id>/
  - otherwise → inlined in the reply. The MCP server can run with no workspace at all
    (Claude Desktop), and creating folders in someone's home directory uninvited is worse
    than a long reply.

Never raises: a deliverable problem must not turn a good answer into an error.
Standard library only — see damira.py.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

DOCS_ENV = "DAMIRA_DOCUMENTS_DIR"    # explicit documents/ folder (tests, sandboxes)
CHANGE_ENV = "DAMIRA_CHANGE_ID"      # the <id> folder name; defaults to a timestamp
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_INLINE_LIMIT = 60_000


def extract(payload: dict) -> "list[dict]":
    """Both payload shapes, de-duplicated, empty content skipped."""
    found, seen = [], set()
    candidates = list(payload.get("deliverables") or [])
    candidates += [m for m in (payload.get("messages") or [])
                   if isinstance(m, dict) and m.get("role") == "deliverable"]
    for d in candidates:
        if not isinstance(d, dict):
            continue
        content = d.get("content")
        if not isinstance(content, str) or not content:
            continue
        name = str(d.get("filename") or "output")
        key = (name, content)
        if key in seen:
            continue
        seen.add(key)
        found.append({"filename": name, "content": content, "type": str(d.get("type") or "docs")})
    return found


def safe_name(filename: str) -> str:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    base = _SAFE.sub("-", base).strip(".-")
    return base or "output"


def _documents_dir() -> "Path | None":
    explicit = os.environ.get(DOCS_ENV, "").strip()
    if explicit:
        return Path(explicit)
    local = Path.cwd() / "documents"
    return local if local.is_dir() else None


def _change_id() -> str:
    cid = safe_name(os.environ.get(CHANGE_ENV, "").strip())
    return cid if cid != "output" else time.strftime("damira-%Y%m%d-%H%M%S")


def _taken(path: Path) -> bool:
    return path.exists() or path.is_symlink()  # a dangling symlink "doesn't exist"


def _unique(path: Path) -> Path:
    if not _taken(path):
        return path
    stem, dot, rest = path.name.partition(".")
    suffix = dot + rest
    n = 2
    while _taken(path.parent / f"{stem}-{n}{suffix}"):
        n += 1
    return path.parent / f"{stem}-{n}{suffix}"


def save(items: "list[dict]") -> "tuple[list[tuple[str, str]], list[dict]]":
    """Write what we can; return ([(display path, type)], [items to inline])."""
    docs = _documents_dir()
    if docs is None:
        return [], items
    folder = docs / _change_id()
    saved, inline = [], []
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return [], items
    for d in items:
        target = _unique(folder / safe_name(d["filename"]))
        try:
            # O_EXCL: never follow or overwrite something planted after _unique looked.
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(d["content"])
        except OSError:
            inline.append(d)
            continue
        try:
            shown = target.relative_to(Path.cwd())
        except ValueError:
            shown = target
        saved.append((shown.as_posix(), d["type"]))
    return saved, inline


def _is_workbook_spec(name: str) -> bool:
    return name.endswith(".damira.json") or name.endswith("workbook.json")


def attach(payload: dict, response: str) -> str:
    """Return the reply with deliverables saved and listed (or inlined). Never raises."""
    try:
        items = extract(payload)
        if not items:
            return response
        saved, inline = save(items)
        lines = []
        if saved:
            lines.append("Damira also returned these files, saved to the workspace:")
            lines += [f"- {path} ({kind})" for path, kind in saved]
            if any(_is_workbook_spec(p) for p, _ in saved):
                lines.append("A .damira.json file is a workbook spec. Render it to .xlsx and an "
                             "HTML preview with `damira workbook <file>`.")
        for d in inline:
            body = d["content"]
            if len(body) > _INLINE_LIMIT:
                body = body[:_INLINE_LIMIT] + "\n… [truncated]"
            runs = re.findall(r"`+", body)
            fence = "`" * max(3, max((len(r) for r in runs), default=0) + 1)
            lines.append(f"Damira deliverable `{safe_name(d['filename'])}` ({d['type']}):\n"
                         f"{fence}\n{body}\n{fence}")
        try:
            import events  # sibling module; logging is best effort
            events.emit({"event": "deliverable_generated", "deliverable_type": "server",
                         "host": os.environ.get("DAMIRA_HOST", "cli"), "status": "saved" if saved else "inline",
                         "counts": {"files": len(items)}})
        except Exception:  # noqa: BLE001
            pass
        return response + "\n\n---\n" + "\n".join(lines)
    except Exception:  # noqa: BLE001 — the answer itself is still good
        return response
