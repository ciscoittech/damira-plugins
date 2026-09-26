#!/usr/bin/env python3
"""Workflow events and telemetry (#475).

One JSON line per workflow run, appended to ~/.damira/logs/workflows.jsonl. The local
file is the source of truth: `damira stats` reads it, and nothing leaves the machine
unless the user opts in with DAMIRA_TELEMETRY=1 (or an eval run sets DAMIRA_ENV=eval).

What an event may hold: rule IDs, check names, statuses, counts, file extensions,
vendor/framework/skill labels, versions, a salted loop hash, attempt numbers, the host
model's name and token counts. What it must never hold: file content, file names or
paths, hostnames, IPs, credentials, tool output, session IDs. Callers pass structured
fields only; `scrub_event` drops unknown keys and any value that looks identifying, using
the same patterns as redact_spec.py (#458).

Schema v2 adds, for #498's premium-vs-cheap view:
  loop     loop_id, attempt, retries, first_pass, time_to_green_ms, final_status
  model    model, model_tier, input_tokens, output_tokens, est_cost_usd (estimates)
  context  environment (development|eval|production), scenario_id (eval runs)

Upload (`flush`) goes to the Damira gateway only, which re-applies the allow-list and
forwards to hosted Langfuse. It is best effort and never raises.

Standard library only — see scripts/damira.py for why.
"""

from __future__ import annotations

import calendar
import contextlib
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

import redact_spec

SCHEMA_VERSION = 2
LOG_ENV = "DAMIRA_LOG_DIR"          # override the directory (tests, sandboxes)
DISABLE_ENV = "DAMIRA_WORKFLOW_LOG"  # "0" turns local logging off
TELEMETRY_ENV = "DAMIRA_TELEMETRY"   # "1" opts in to the scrubbed upload
ENV_ENV = "DAMIRA_ENV"               # development | eval | production
SCENARIO_ENV = "DAMIRA_EVAL_SCENARIO"
MODEL_ENV = "DAMIRA_MODEL"           # set by eval harnesses when the host can't report it
UPLOAD_PATH = "/api/extension/telemetry"
BATCH_SIZE = 100
UPLOAD_TIMEOUT = 5

_ENUMS = {
    "event": {"validate", "deliverable_generated", "eval"},
    "status": {"pass", "fail", "warn", "unverified", "empty", "skipped", "error"},
    "final_status": {"pass", "warn"},
    "host": {"cli", "claude-code", "cursor", "other"},
    "environment": {"development", "eval", "production"},
    "model_tier": {"premium", "standard", "cheap", "unknown"},
}
_INTS = {"schema_version", "duration_ms", "attempt", "retries", "time_to_green_ms",
         "input_tokens", "output_tokens"}
_FLOATS = {"est_cost_usd", "grounded_pct"}
_LABELS = {"skill", "framework", "vendor", "plugin_version", "deliverable_type", "model", "scenario_id"}
# Labels set by Damira or the host, not by the user's files: model names (claude-opus-4-5)
# and eval scenario IDs (ospf-area-mismatch-01) look hostname-like but aren't.
_HOSTLIKE_OK = {"model", "scenario_id", "plugin_version"}
_EVENT_KEYS = (set(_ENUMS) | _INTS | _FLOATS | _LABELS
               | {"ts", "run_id", "loop_id", "first_pass", "counts", "checks", "file_types"})
_COUNT_KEYS = {"pass", "fail", "warn", "skipped", "nodes", "links"}  # nodes/links: diagram size (#485)

_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\[\]-]{0,79}$")
_EXT = re.compile(r"^(?:\.[a-z0-9]{1,8}|dir|none|)$")
_TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")

# First match wins. Tiers and prices are local estimates, labeled as such in `stats`.
# USD per million tokens (input, output), list prices.
_MODELS = (
    ("fable", "premium", 10.0, 50.0),
    ("mythos", "premium", 10.0, 50.0),
    ("opus-5-5", "premium", 4.0, 20.0),
    ("opus", "premium", 5.0, 25.0),
    ("sonnet-5", "standard", 2.0, 10.0),
    ("sonnet", "standard", 3.0, 15.0),
    ("haiku", "cheap", 1.0, 5.0),
    ("gpt-5-nano", "cheap", 0.05, 0.40),
    ("gpt-5-mini", "cheap", 0.25, 2.0),
    ("gpt-5", "premium", 1.25, 10.0),
    ("gemini-2.5-pro", "premium", 1.25, 10.0),
    ("flash", "cheap", 0.30, 2.50),
    ("gemma", "cheap", 0.10, 0.30),
    ("deepseek", "cheap", 0.30, 1.20),
    ("qwen", "cheap", 0.20, 0.80),
    ("kimi", "standard", 0.60, 2.50),
    ("grok", "standard", 3.0, 15.0),
)


# --- paths -------------------------------------------------------------------------

def log_path() -> Path:
    base = os.environ.get(LOG_ENV, "").strip()
    return (Path(base) if base else Path.home() / ".damira" / "logs") / "workflows.jsonl"


def _state_dir() -> Path:
    """~/.damira normally; the log dir's parent under DAMIRA_LOG_DIR (tests)."""
    return log_path().parent.parent


# --- models --------------------------------------------------------------------------

def normalize_model(model) -> "str | None":
    if not isinstance(model, str) or not model.strip():
        return None
    name = model.strip().lower().split("[")[0]
    name = re.sub(r"-20\d{6}$", "", name)  # dated snapshot suffix
    return name if _LABEL.match(name) else None


def _model_row(model: "str | None"):
    for needle, tier, price_in, price_out in _MODELS if model else ():
        if needle in model:
            return tier, price_in, price_out
    return None


def model_tier(model: "str | None") -> "str | None":
    if not model:
        return None
    row = _model_row(model)
    return row[0] if row else "unknown"


def estimate_cost(model, input_tokens, output_tokens, cache_read: int = 0, cache_write: int = 0):
    """Estimated USD at list price. Cache reads bill ~0.1x input, writes ~1.25x."""
    row = _model_row(normalize_model(model))
    if not row or input_tokens is None or output_tokens is None:
        return None
    _, price_in, price_out = row
    fresh = max(int(input_tokens) - cache_read - cache_write, 0)
    usd = (fresh + 0.1 * cache_read + 1.25 * cache_write) * price_in + int(output_tokens) * price_out
    return round(usd / 1_000_000, 6)


# --- scrub ---------------------------------------------------------------------------

def _identifying(value: str, hostlike_ok: bool = False) -> bool:
    """True if redact_spec would change the value: an IP, MAC, email, FQDN, serial,
    secret or token, or (unless hostlike_ok) a hostname-like name."""
    probe = redact_spec._HOSTLIKE.sub("x", value) if hostlike_ok else value
    return redact_spec._scrub(probe, redact_spec._Tokens()) != probe


def _label(key: str, value) -> "str | None":
    if not isinstance(value, str) or not _LABEL.match(value):
        return None
    return None if _identifying(value, key in _HOSTLIKE_OK) else value


def _number(value, kind):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value) if kind is int else round(float(value), 6)


def _clean_value(key: str, value):
    if value is None:
        return None
    if key in _ENUMS:
        return value if value in _ENUMS[key] else None
    if key in _INTS:
        return _number(value, int)
    if key in _FLOATS:
        return _number(value, float)
    if key in _LABELS:
        return _label(key, value)
    if key == "first_pass":
        return value if isinstance(value, bool) else None
    if key == "ts":
        return value if isinstance(value, str) and _TS.match(value) else None
    if key == "run_id":
        return value if isinstance(value, str) and _UUID.match(value) else None
    if key == "loop_id":
        return value if isinstance(value, str) and _HEX16.match(value) else None
    if key == "counts":
        if not isinstance(value, dict):
            return None
        return {k: v for k, v in value.items() if k in _COUNT_KEYS and _number(v, int) is not None}
    if key == "file_types":
        return [v for v in value if isinstance(v, str) and _EXT.match(v)] if isinstance(value, list) else None
    if key == "checks":
        return [_clean_check(c) for c in value if isinstance(c, dict)] if isinstance(value, list) else None
    return None


def _clean_check(check: dict) -> dict:
    out = {}
    if _label("check", check.get("check")):
        out["check"] = check["check"]
    if check.get("status") in _ENUMS["status"]:
        out["status"] = check["status"]
    if isinstance(check.get("ext"), str) and _EXT.match(check["ext"]):
        out["ext"] = check["ext"]
    out["rule_ids"] = [r for r in check.get("rule_ids") or [] if _label("rule_id", r)]
    return out


def scrub_event(event: dict) -> dict:
    """Keep allow-listed keys whose values have the expected shape and identify nothing.
    Anything else is dropped, never rewritten: a mangled value is still a leak."""
    clean = {}
    for key, value in event.items():
        if key in _EVENT_KEYS:
            value = _clean_value(key, value)
            if value is not None:
                clean[key] = value
    return clean


# --- loops ---------------------------------------------------------------------------

def _salt() -> str:
    path = _state_dir() / "telemetry_salt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    salt = secrets.token_hex(16)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(salt)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return salt


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:16]


def recent_events(max_bytes: int = 2_000_000) -> "list[dict]":
    """Parsed events from the tail of the local log (bounded read)."""
    path = log_path()
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(size - max_bytes, 0))
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = data.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]  # first line is probably partial
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def _epoch(ts: str) -> "float | None":
    try:
        return float(calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def loop_fields(target, session_id, status: str, duration_ms: int) -> dict:
    """loop_id/attempt/first_pass/time_to_green_ms for one validate run.

    A loop is one file in one host session, until it goes green (pass or warn); the next
    validation after that starts a new loop. loop_id is a salted hash: the salt stays in
    ~/.damira/telemetry_salt, so the ID can't be mapped back to a path or session."""
    salt, key = _salt(), str(target)
    session = session_id if isinstance(session_id, str) and session_id else "no-session"
    prior = [e for e in recent_events() if e.get("event") == "validate" and e.get("loop_id")]
    generation = 0
    while True:
        loop_id = _hash(salt, session, key, str(generation))
        mine = [e for e in prior if e.get("loop_id") == loop_id]
        if not any(e.get("final_status") for e in mine):
            break
        generation += 1
    attempt = len(mine) + 1
    green = status in ("pass", "warn")
    fields = {"loop_id": loop_id, "attempt": attempt, "retries": attempt - 1,
              "first_pass": green and attempt == 1, "final_status": status if green else None,
              "time_to_green_ms": None}
    if green:
        started = _epoch(mine[0].get("ts")) if mine else None
        fields["time_to_green_ms"] = (duration_ms if started is None
                                      else max(int((time.time() - started) * 1000), duration_ms))
    return fields


def model_fields(model=None, input_tokens=None, output_tokens=None, cache_read: int = 0,
                 cache_write: int = 0) -> dict:
    name = normalize_model(model or os.environ.get(MODEL_ENV))
    return {"model": name, "model_tier": model_tier(name), "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "est_cost_usd": estimate_cost(name, input_tokens, output_tokens, cache_read, cache_write)}


# --- emit ----------------------------------------------------------------------------

def environment() -> str:
    env = os.environ.get(ENV_ENV, "").strip().lower()
    return env if env in _ENUMS["environment"] else "production"


def emit(event: dict) -> "Path | None":
    """Append one event. Never raises: logging must not break validation."""
    if os.environ.get(DISABLE_ENV, "").strip() == "0":
        return None
    env = environment()
    base = {"schema_version": SCHEMA_VERSION,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "environment": env}
    if env == "eval":
        base["scenario_id"] = os.environ.get(SCENARIO_ENV, "").strip() or None
    event = scrub_event({**base, **event})
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
        return path
    except OSError:
        return None


@contextlib.contextmanager
def eval_context(scenario_id: str, model: "str | None" = None, host: "str | None" = None):
    """Tag every event emitted inside (and by hook subprocesses that inherit the env) as
    an eval run of `scenario_id`. Eval events always upload, whatever DAMIRA_TELEMETRY
    says (#476). `host` is accepted for the harness's convenience; events record the
    host that actually ran."""
    del host
    saved = {k: os.environ.get(k) for k in (ENV_ENV, SCENARIO_ENV, MODEL_ENV)}
    os.environ[ENV_ENV] = "eval"
    os.environ[SCENARIO_ENV] = scenario_id
    if model:
        os.environ[MODEL_ENV] = model
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --- upload --------------------------------------------------------------------------

def telemetry_enabled() -> bool:
    return os.environ.get(TELEMETRY_ENV, "").strip() == "1"


def _read_cursor(path: Path, log: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    # First flush after opting in: history recorded before consent stays local. Start
    # at the last line, which is the event the current run just wrote.
    try:
        data = log.read_bytes()
    except OSError:
        return 0
    return data.rstrip(b"\n").rfind(b"\n") + 1


def flush() -> int:
    """Upload unsent events to the gateway. Returns how many were accepted.

    Runs only when DAMIRA_TELEMETRY=1 (all events) or in an eval run (eval events
    only). Otherwise returns 0 before touching the network or any state. Never raises."""
    opted_in, evaluating = telemetry_enabled(), environment() == "eval"
    if not (opted_in or evaluating):
        return 0
    try:
        return _flush(opted_in)
    except Exception:  # noqa: BLE001 — telemetry must never break a workflow
        return 0


def _flush(opted_in: bool) -> int:
    import urllib.request

    import damira  # key resolution and User-Agent live there

    key, is_demo = damira.resolve_key()
    if is_demo:
        return 0  # the shared demo key isn't tied to a user; nothing to attribute to
    # Separate cursors: an eval-only flush must not move the opt-in cursor, or events
    # recorded between an eval run and a later opt-in would upload without consent.
    log = log_path()
    cursor_path = _state_dir() / ("telemetry_sent" if opted_in else "telemetry_sent_eval")
    offset = _read_cursor(cursor_path, log)
    with open(log, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    end = data.rfind(b"\n") + 1  # only whole lines
    pending = []  # (event, cursor offset just past its line)
    pos = offset
    for raw in data[:end].split(b"\n")[:-1]:
        pos += len(raw) + 1
        try:
            ev = scrub_event(json.loads(raw.decode("utf-8", errors="replace")))
        except (ValueError, AttributeError):
            continue
        if opted_in or ev.get("environment") == "eval":
            pending.append((ev, pos))
    api_url = os.environ.get("DAMIRA_API_URL", damira.DEFAULT_API_URL).rstrip("/")
    sent = 0
    for i in range(0, len(pending), BATCH_SIZE):
        chunk = pending[i:i + BATCH_SIZE]
        req = urllib.request.Request(
            api_url + UPLOAD_PATH,
            data=json.dumps({"events": [ev for ev, _ in chunk]}).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "User-Agent": damira.USER_AGENT},
            method="POST")
        with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT) as resp:
            if resp.status >= 300:
                return sent
        sent += len(chunk)
        _write_cursor(cursor_path, chunk[-1][1])
    _write_cursor(cursor_path, offset + end)
    return sent


def _write_cursor(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset), encoding="utf-8")
