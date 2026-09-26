#!/usr/bin/env python3
"""Workbook grounding check (#484). Started as a stdlib port of the server's
_verify_workbook_grounding (services/oncall-agent/src/spreadsheet_pipeline.py), and is now
much stricter than it. The server's 0.6 fuzzy match passed `write erase` against
`write memory`, a 17.06.05 image against 17.09.05 evidence, `shutdown` against
`no shutdown` and an install command with `commit` dropped. So there is no fuzzy match:
a cell matches only where the evidence contains the same command as whole words (spacing
and case ignored), on one line, not negated by a `no` in front, and a `no ...` cell needs
the `no` too. The evidence command must also end where the cell ends (line end,
punctuation, or a prose word such as "to"/"then"; after set/delete/deactivate/activate,
"from"/"then"/"to" are Junos policy and filter keywords, not prose): `commit` is not backed by
`commit check`, nor `reload` by `reload in 10`. Only read-only verbs (show, display...)
may be a shorter form. A one-word command (`reload`, `delete [IMAGE]`) only counts at the
start of a line, after a prompt, or in quotes, never as a word in a sentence. A line that
warns about a command ("Never run: write erase", "Avoid reload") is not evidence. A
<placeholder> stands for exactly one value word on the same line, and after a trailing
placeholder's value the evidence command must end too (`clear ip bgp [NEIGHBOR]` is not
backed by `clear ip bgp 10.1.1.1 soft in`). A cell that is only placeholders is never backed.

Command-like cells are what an engineer pastes into a production device, so each one is
cross-referenced against the evidence Damira actually returned (saved by the skill to
documents/<id>/evidence/). Cells with no match are tagged UNVERIFIED in a Grounding
column. Same contract as the server: tag, never rewrite. A corrupted command is worse
than an unflagged one.

Standard library only, so the document gate and the Cursor path can run it
without uv.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

# Header names (case-insensitive) whose cells are always commands.
GROUNDING_HEADER_KEYS = {"verification command", "cli command", "command"}
# Columns that hold a command in some rows and prose in others ("Check",
# "Rollback", ...). Only cells that start with a CLI verb are checked there.
MIXED_HEADER_KEYS = {"check", "rollback", "rollback command", "remediation", "details"}
_CLI_VERBS = {
    "show", "no", "install", "request", "set", "unset", "delete", "configure", "conf", "commit",
    "rollback", "copy", "write", "reload", "clear", "debug", "interface", "router", "ip", "ipv6",
    "neighbor", "shutdown", "format", "erase", "load", "save", "username", "snmp-server", "crypto",
    "license", "boot", "system", "upgrade", "restore", "execute", "diagnose", "get", "test", "ping",
    "traceroute", "terminal", "run", "monitor", "vlan", "spanning-tree", "feature", "hostname",
    "archive", "dir", "verify", "redundancy", "switch", "logging", "ntp", "aaa", "route-map",
    "access-list", "line", "service", "class-map", "policy-map", "end", "exit", "activate",
    # CUCM/UC (utils ...), FortiOS (config/edit/next), IOS-XR admin mode, file ops.
    "utils", "config", "edit", "next", "append", "unselect", "purge", "admin", "file", "more",
    "cd", "mkdir", "rmdir", "del", "rename", "start", "stop", "enable", "disable",
}
# Cell prefixes that say "this is not a command": skipped, not tagged UNVERIFIED.
_NOT_A_COMMAND = ("[VERIFY", "GUI:", "Manual:")
GROUNDING_HEADER = "Grounding"
MATCHED = "source-matched"
UNVERIFIED = "UNVERIFIED"

_EVIDENCE_SUFFIXES = {".md", ".txt", ".json", ".log", ".cfg"}


_WORD = re.compile(r"[a-z0-9][a-z0-9._:/-]*[a-z0-9]|[a-z0-9]")
_PLACEHOLDER = re.compile(r"<[^>]*>|\[[^\]]*\]|\{[^}]*\}")


def words(text: str) -> "set[str]":
    """Lower-case words and values (17.09.05, bootflash:cat9k, 0/1), placeholders dropped."""
    return set(_WORD.findall(_PLACEHOLDER.sub(" ", text.lower())))


def looks_like_cli(value: str) -> bool:
    first = value.strip().split(None, 1)
    return bool(first) and first[0] in _CLI_VERBS


# Read-only verbs: a cell that is a shorter form of an evidence command is still safe.
_READ_ONLY = {"show", "display", "dir", "ping", "traceroute", "more", "get"}
# Words after a match that mean the sentence moved on, so the command ended there.
# Anything else (`commit check`, `reload in 10`, `clear ip bgp * soft in`) means the
# evidence command is longer than the cell, which does something else. "at" is left out:
# `reload at 02:00` and `commit at "02:00"` are scheduled commands, not a sentence moving on.
_PROSE_NEXT = {"to", "and", "then", "before", "after", "on", "the", "a", "an", "is", "are", "was",
               "were", "for", "from", "with", "first", "again", "or", "if", "when", "which", "that",
               "it", "this", "will", "should", "must", "can", "command", "commands", "output",
               "until", "so", "but", "as", "by", "once", "instead", "also", "only", "while"}
# Prose words that are also Junos policy/filter keywords (`term T from ...`, `term T then
# reject`, `term T to neighbor ...`). After a Junos configuration verb they continue the
# command, never end it: `delete ... term ALLOW-SSH` is not backed by
# `delete ... term ALLOW-SSH from source-address X`. After other verbs they stay prose
# (`write memory to save`).
_CLI_KEYWORDS = {"from", "then", "to"}
_CONFIG_VERBS = {"set", "delete", "deactivate", "activate", "insert", "edit", "unset", "replace",
                 "rename", "protect", "unprotect"}
_WORD_CHAR = re.compile(r"[\w-]")
_NEXT_TOKEN = re.compile(r" ([^\s]+)")
_PROSE_THEN_VALUE = re.compile(r" [^\s]+ [`'\"(]*\d")
# What may sit before a one-word command on its line: nothing, a bullet or step number,
# a prompt (#, >, $), a colon, or an opening quote/backtick. `reload` in "save before
# reload." is prose, not evidence for a reload.
_CMD_LEAD = re.compile(r"(?:^\s*(?:[-*\u2022]|\d+[.)])?|[`'\"#>$:(])\s*$")
# A line that warns about a command is not evidence for running it.
_WARNING = re.compile(r"\b(?:never|do not|don't|dont|avoid|warning|caution|danger(?:ous)?|only if|unless|"
                      r"must not|should not|not recommended)\b", re.I)
_LOOK_BACK = 200
_LOOK_AHEAD = 400


def _norm(text: str) -> str:
    """Runs of spaces collapsed, line breaks kept (a command is one line). Case is kept so a
    capitalised sentence ("Delete old files") can be told from a command; matching ignores it."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r" *\n[ \n]*", "\n", text).strip()


def _bare(token: str) -> str:
    return token.strip("`'\".,;:()")


def _command_ends(corpus: str, end: int, config: bool = False) -> bool:
    """True if the evidence command stops at `end` (line end, punctuation, or prose)."""
    if end >= len(corpus) or corpus[end] != " ":
        return True
    nxt = _NEXT_TOKEN.match(corpus, end)
    word = _bare(nxt.group(1)).lower() if nxt else ""
    if word not in _PROSE_NEXT or (config and word in _CLI_KEYWORDS):
        return False
    # A prose word followed by a time or number (`on 12 March`, `for 5`) is an argument.
    return not _PROSE_THEN_VALUE.match(corpus, end)


def _values_then_end(corpus: str, pos: int, count: int, read_only: bool, config: bool) -> bool:
    """Trailing placeholders: each takes exactly one value token on the same line, and the
    evidence command must end right after the last one. `clear ip bgp [NEIGHBOR]` is not
    backed by `clear ip bgp 10.1.1.1 soft in`: that is a different (soft) reset."""
    for _ in range(count):
        nxt = _NEXT_TOKEN.match(corpus, pos)
        word = _bare(nxt.group(1)).lower() if nxt else ""
        if not word or word in _PROSE_NEXT:
            return False
        pos = nxt.end()
    return read_only or _command_ends(corpus, pos, config)


def _occurs(phrase: str, corpus: str, negated: bool) -> "list[tuple[int, int]]":
    """(start, end) of whole-word occurrences of phrase that are not negated."""
    spans = []
    for m in re.finditer(re.escape(phrase), corpus, re.I):
        start, end = m.start(), m.end()
        if start and _WORD_CHAR.match(corpus[start - 1]) and _WORD_CHAR.match(phrase[0]):
            continue  # inside a longer word
        if end < len(corpus) and _WORD_CHAR.match(corpus[end]) and _WORD_CHAR.match(phrase[-1]):
            continue
        # 11.1.3 is not 11.1.3.1: a dot between two value characters joins them.
        if end + 1 < len(corpus) and corpus[end] == "." and corpus[end + 1].isalnum() and phrase[-1].isalnum():
            continue
        if start > 1 and corpus[start - 1] == "." and corpus[start - 2].isalnum() and phrase[0].isalnum():
            continue
        if not negated and corpus[max(0, start - 3):start].lower() == "no ":
            continue  # the evidence says the opposite
        spans.append((start, end))
    return spans


def _line_bounds(corpus: str, start: int, end: int) -> "tuple[int, int, bool]":
    """(line start, line end, whether the real line start was found) within a bounded window,
    so one huge evidence line cannot make the scan quadratic."""
    lo = max(0, start - _LOOK_BACK)
    line_start = corpus.rfind("\n", lo, start) + 1
    found = line_start > 0 or lo == 0
    if not found:
        line_start = lo
    hi = min(len(corpus), end + _LOOK_AHEAD)
    line_end = corpus.find("\n", end, hi)
    return line_start, (hi if line_end < 0 else line_end), found


def _in_command_position(corpus: str, start: int, line_start: int, found: bool) -> bool:
    if corpus[start].isupper():
        return False  # "Delete the old image..." starts a sentence; CLI verbs are lower case
    lead = corpus[line_start:start]
    return bool(_CMD_LEAD.search(lead if found else "x" + lead))


def _parse(needle: str) -> "tuple[list[tuple[str, int]], int]":
    """Literal parts with the number of placeholders before each, and the trailing count."""
    parts, gap = [], 0
    for i, piece in enumerate(_PLACEHOLDER.split(needle)):
        gap += 1 if i else 0
        if piece.strip():
            parts.append((piece.strip(), gap))
            gap = 0
    return parts, gap


def _line_grounded(needle: str, corpus: str) -> bool:
    negated = needle.startswith("no ")
    parts, trailing = _parse(needle)
    if not parts:
        return False  # placeholder-only: there is nothing to match, so nothing is backed
    first = parts[0][0]
    verb = first.split(" ", 1)[0]
    read_only, config = verb in _READ_ONLY, verb in _CONFIG_VERBS
    for start, end in _occurs(first, corpus, negated):
        line_start, line_end, found = _line_bounds(corpus, start, end)
        if " " not in first and not read_only and not _in_command_position(corpus, start, line_start, found):
            continue  # a lone verb inside prose
        if _WARNING.search(corpus, line_start, line_end):
            continue  # "Never run: write erase" is a warning, not evidence
        pos, ok = end, True
        for part, gap in parts[1:]:
            ok = False
            for s2, e2 in _occurs(part, corpus[pos:line_end], True):
                # Each placeholder between two literal parts stands for exactly one value.
                if len(corpus[pos:pos + s2].split()) == gap:
                    pos, ok = pos + e2, True
                    break
            if not ok:
                break
        if not ok:
            continue
        if trailing:
            if _values_then_end(corpus, pos, trailing, read_only, config):
                return True
        elif read_only or _command_ends(corpus, pos, config):
            return True
    return False


def grounded_in(needle: str, corpus: str) -> bool:
    """True if the evidence contains this command, with its meaning intact (see module doc).
    `corpus` must already be normalised with _norm(). A multi-line cell needs every line."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in needle.lower().splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return True
    if not corpus:
        return False
    return all(_line_grounded(line, corpus) for line in lines)


def fuzzy_contains(needle: str, corpus_lower: str, **_ignored) -> bool:
    """Kept for callers of the old name; there is no fuzzy match any more."""
    return grounded_in(needle, _norm(corpus_lower))


def load_corpus(evidence_dir: "str | Path | None") -> str:
    """Concatenate every evidence file under the folder. Missing folder = empty corpus."""
    if not evidence_dir:
        return ""
    root = Path(evidence_dir)
    if not root.is_dir():
        return ""
    parts = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in _EVIDENCE_SUFFIXES:
            try:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(parts)


def _row_value(row: dict, header: str):
    key = header.lower().replace(" ", "_")
    return row.get(key) or row.get(header)


def ground_spec(spec: dict, corpus: str) -> "tuple[dict, int, int]":
    """Return (tagged copy of spec, unverified count, checked count). Input is untouched."""
    spec = copy.deepcopy(spec)
    corpus_norm = _norm(corpus)
    checked = unverified = 0

    for sheet in spec.get("sheets", []) or []:
        headers = sheet.get("headers", []) or []
        command_headers = [h for h in headers if isinstance(h, str)
                           and h.strip().lower() in GROUNDING_HEADER_KEYS | MIXED_HEADER_KEYS]
        if not command_headers:
            continue
        for row in sheet.get("rows", []) or []:
            if not isinstance(row, dict):
                continue
            row_checked = False
            row_grounded = True
            for header in command_headers:
                val = _row_value(row, header)
                if not isinstance(val, str) or not val.strip():
                    continue
                if val.strip().lower().startswith(tuple(p.lower() for p in _NOT_A_COMMAND)):
                    continue  # self-flagged, or a GUI/manual step with no command to match
                if header.strip().lower() in MIXED_HEADER_KEYS and not looks_like_cli(val):
                    continue  # prose ("Record stack priorities"), not a command
                row_checked = True
                checked += 1
                if not grounded_in(val, corpus_norm):
                    row_grounded = False
                    unverified += 1
            if row_checked:
                row["grounding"] = MATCHED if row_grounded else UNVERIFIED
        if GROUNDING_HEADER not in headers:
            headers.append(GROUNDING_HEADER)
            sheet["headers"] = headers

    if unverified:
        note = (f"{unverified} of {checked} steps could not be matched to the saved Damira "
                "evidence and are marked UNVERIFIED. Verify them before executing in production.")
        summary = spec.get("executive_summary", "")
        spec["executive_summary"] = f"{summary}\n\n{note}" if summary else note
    return spec, unverified, checked


def grounded_pct(unverified: int, checked: int) -> "int | None":
    if not checked:
        return None
    return round(100 * (checked - unverified) / checked)


def summary_line(unverified: int, checked: int, corpus_empty: bool) -> str:
    if not checked:
        return "Grounding: no command cells to check."
    line = (f"Grounding: {checked - unverified} of {checked} command cells matched the evidence "
            f"({grounded_pct(unverified, checked)}%).")
    if unverified:
        line += f" {unverified} marked UNVERIFIED. Verify before executing."
    if corpus_empty:
        line += (" No evidence was found, so nothing could be matched. Save the Damira "
                 "lookups to the evidence/ folder next to workbook.json and render again.")
    return line


def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description="Tag workbook command cells that the evidence does not back")
    p.add_argument("spec", help="workbook.json (WorkbookSpec)")
    p.add_argument("--evidence", default="", help="evidence folder (default: <spec dir>/evidence)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    spec_path = Path(a.spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    evidence = Path(a.evidence) if a.evidence else spec_path.parent / "evidence"
    corpus = load_corpus(evidence)
    _, unverified, checked = ground_spec(spec, corpus)
    if a.json:
        print(json.dumps({"checked": checked, "unverified": unverified,
                          "grounded_pct": grounded_pct(unverified, checked)}))
    else:
        print(summary_line(unverified, checked, not corpus))
    return 0


if __name__ == "__main__":
    sys.exit(main())
