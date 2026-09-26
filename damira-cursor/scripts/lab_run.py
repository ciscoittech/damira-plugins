#!/usr/bin/env python3
"""damira lab — test a change in a ContainerLab lab before production (#477).

    damira lab preflight                 docker, containerlab, daemon -> mode lab | validate-only
    damira lab validate <topo.clab.yml>  topology sanity, no docker needed
    damira lab run <topo.clab.yml> [--before CMD] [--apply change.yml] [--checks lab.checks.json]
                                         deploy -> before -> apply -> checks -> report -> destroy

Teardown lives in a `finally`, so a failed apply, a failed check, an exception or Ctrl-C
still runs `containerlab destroy --cleanup`. Without docker or containerlab the run
degrades to validate-only and the report says the change was NOT lab-tested.

Checks use the eval harness StateCheck shape (services/oncall-agent/labs/harness/schema.py):
command + regex | contains | equals | exists, wait_s; `output: true` matches the apply
output. `{lab}` in a command expands to the lab name. Stdlib only; the command runner is
injectable so tests never touch docker.
"""

import argparse
import json
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

APPLY_TIMEOUT = 900
CHECK_TIMEOUT = 120
CLAB_TIMEOUT = 600
_SPECIAL_ENDPOINTS = {"host", "mgmt-net", "macvlan"}
_UNSET = object()


# ── command runner ──────────────────────────────────────────────────────────

def default_runner(cmd: "list[str]", timeout: "float | None" = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(cmd, 124, out, f"timed out after {timeout}s")
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


# ── minimal YAML reader (the subset ContainerLab topologies use) ────────────

def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if ch in "\"'" and quote in (None, ch):
            quote = None if quote else ch
        elif ch == "#" and quote is None and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _split_flow(body: str) -> "list[str]":
    parts, buf, quote, depth = [], "", None, 0
    for ch in body:
        if ch in "\"'" and quote in (None, ch):
            quote = None if quote else ch
        elif quote is None and ch in "[{":
            depth += 1
        elif quote is None and ch in "]}":
            depth -= 1
        if ch == "," and quote is None and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _scalar(text: str):
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(p) for p in _split_flow(text[1:-1])]
    if text.startswith("{") and text.endswith("}"):
        out = {}
        for part in _split_flow(text[1:-1]):
            k, _, v = part.partition(":")
            out[_scalar(k)] = _scalar(v)
        return out
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("", "~", "null"):
        return None
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


_KEY = re.compile(r"""^("[^"]*"|'[^']*'|[^\s"'\[{#-][^:]*?|-[^\s:][^:]*?):(?:\s+(.*))?$""")


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _block(lines, i, indent):
    if _is_item(lines[i][1]):
        return _seq(lines, i, indent)
    return _map(lines, i, indent)


def _child(lines, i, indent, allow_seq_same_indent):
    if i < len(lines) and (lines[i][0] > indent or
                           (allow_seq_same_indent and lines[i][0] == indent and _is_item(lines[i][1]))):
        return _block(lines, i, lines[i][0])
    return None, i


def _map(lines, i, indent):
    out = {}
    while i < len(lines) and lines[i][0] == indent and not _is_item(lines[i][1]):
        m = _KEY.match(lines[i][1])
        if not m:
            raise ValueError(f"line {lines[i][2]}: expected 'key: value', got {lines[i][1]!r}")
        key, rest = _scalar(m.group(1)), (m.group(2) or "").strip()
        i += 1
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            buf = []
            while i < len(lines) and lines[i][0] > indent:
                buf.append(lines[i][1])
                i += 1
            out[key] = "\n".join(buf)
        elif rest:
            out[key] = _scalar(rest)
        else:
            out[key], i = _child(lines, i, indent, True)
    return out, i


def _seq(lines, i, indent):
    out = []
    while i < len(lines) and lines[i][0] == indent and _is_item(lines[i][1]):
        rest = lines[i][1][1:].strip()
        if not rest:
            value, i = _child(lines, i + 1, indent, False)
        elif _KEY.match(rest) and not rest.startswith(("[", "{")):
            # "- key: v" opens a mapping whose other keys sit at the column of "key".
            lines[i] = (indent + len(lines[i][1]) - len(rest), rest, lines[i][2])
            value, i = _map(lines, i, lines[i][0])
        else:
            value, i = _scalar(rest), i + 1
        out.append(value)
    return out, i


def load_yaml(text: str):
    """Parse YAML: PyYAML when installed, else a stdlib reader for the block/flow subset a
    ContainerLab topology uses (maps, lists, [flow], quoted scalars, comments)."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        pass
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.strip() in ("---", "..."):
            continue
        line = _strip_comment(raw)
        if line.strip():
            lines.append((len(line) - len(line.lstrip(" ")), line.strip(), n))
    if not lines:
        return None
    value, i = _block(lines, 0, lines[0][0])
    if i < len(lines):
        raise ValueError(f"line {lines[i][2]}: unexpected indentation")
    return value


# ── validate ────────────────────────────────────────────────────────────────

def _endpoint_node(ep):
    if isinstance(ep, dict):
        return str(ep.get("node", ""))
    return str(ep).split(":", 1)[0] if ":" in str(ep) else ""


def validate_topology(path) -> dict:
    """Sanity-check a ContainerLab topology without docker: name, nodes with a kind, link
    endpoints that name defined nodes, startup-config files that exist."""
    path = Path(path)
    result = {"ok": False, "topology": str(path), "name": "", "nodes": [], "errors": []}
    errors = result["errors"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read topology: {exc}")
        return result
    try:
        import validate  # reuse `damira validate`'s tab rule: every YAML parser rejects tabs
        tab = validate._stdlib_yaml(path, text)
        if tab.get("status") == "fail":
            errors.append(tab.get("detail") or "tab indentation")
            return result
    except Exception:  # validate.py is optional here; the parser below still runs
        pass
    try:
        doc = load_yaml(text)
    except Exception as exc:  # PyYAML raises its own error types
        errors.append(f"YAML does not parse: {exc}")
        return result
    if not isinstance(doc, dict):
        errors.append("topology file is not a YAML mapping")
        return result

    name = doc.get("name")
    if not name or not isinstance(name, str):
        errors.append("missing top-level 'name'")
    result["name"] = name if isinstance(name, str) else ""
    topo = doc.get("topology") if isinstance(doc.get("topology"), dict) else {}
    nodes = topo.get("nodes") if isinstance(topo.get("nodes"), dict) else {}
    if not nodes:
        errors.append("no nodes under 'topology.nodes'")
    kinds = topo.get("kinds") if isinstance(topo.get("kinds"), dict) else {}
    default_kind = (topo.get("defaults") or {}).get("kind") if isinstance(topo.get("defaults"), dict) else None
    base = path.parent
    for node, spec in nodes.items():
        spec = spec if isinstance(spec, dict) else {}
        kind = spec.get("kind") or default_kind
        if not kind:
            errors.append(f"node {node}: no 'kind' (and no topology.defaults.kind)")
        kind_spec = kinds.get(kind) if isinstance(kinds.get(kind), dict) else {}
        cfg = spec.get("startup-config") or kind_spec.get("startup-config")
        if isinstance(cfg, str) and "\n" not in cfg and not (base / cfg).expanduser().exists():
            errors.append(f"node {node}: startup-config {cfg} not found (relative to {base})")
    result["nodes"] = [str(n) for n in nodes]

    for n, link in enumerate(topo.get("links") or [], 1):
        eps = link.get("endpoints") if isinstance(link, dict) else None
        if isinstance(link, dict) and not eps and isinstance(link.get("endpoint"), dict):
            eps = [link["endpoint"]]
        if not isinstance(eps, list) or not eps:
            errors.append(f"link {n}: no endpoints")
            continue
        for ep in eps:
            node = _endpoint_node(ep)
            if not node:
                errors.append(f"link {n}: endpoint {ep!r} is not node:interface")
            elif node not in nodes and node not in _SPECIAL_ENDPOINTS:
                errors.append(f"link {n}: endpoint {ep!r} names undefined node '{node}'")
    result["ok"] = not errors
    return result


# ── preflight ───────────────────────────────────────────────────────────────

def _clab_bin(which) -> "str | None":
    return which("containerlab") or which("clab")


def preflight(runner=default_runner, which=shutil.which) -> dict:
    """lab mode needs docker, a running daemon, and containerlab; anything missing -> validate-only."""
    missing = [n for n, found in (("docker", which("docker")), ("containerlab", _clab_bin(which)))
               if not found]
    if missing:
        return {"mode": "validate-only", "reason": f"{' and '.join(missing)} not installed",
                "missing": missing}
    info = runner(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
    if info.returncode != 0:
        return {"mode": "validate-only", "reason": "docker daemon is not running", "missing": ["docker daemon"]}
    return {"mode": "lab", "reason": "docker and containerlab available", "missing": [],
            "containerlab": _clab_bin(which)}


# ── checks (StateCheck semantics) ───────────────────────────────────────────

_CHECK_FIELDS = {"node", "path", "datastore", "equals", "contains", "exists", "wait_s",
                 "command", "output", "regex"}


def load_checks(path) -> "list[dict]":
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    checks = data.get("checks", data) if isinstance(data, dict) else data
    if not isinstance(checks, list):
        raise ValueError("checks file must be a list of checks (or {\"checks\": [...]})")
    for n, c in enumerate(checks, 1):
        extra = set(c) - _CHECK_FIELDS if isinstance(c, dict) else {"<not an object>"}
        if extra:
            raise ValueError(f"check {n}: unknown field(s) {sorted(extra)} — use the harness StateCheck fields")
    return checks


def _unwrap(value):
    while isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
    return value


def matches(check: dict, value) -> bool:
    """Same order and semantics as StateCheck.matches: regex, equals, contains, exists."""
    if check.get("regex") is not None:
        text = value if isinstance(value, str) else json.dumps(value)
        return value is not None and re.search(check["regex"], text, re.M) is not None
    equals = check.get("equals", _UNSET)
    if equals is not _UNSET:
        return _unwrap(value) == equals or str(_unwrap(value)) == str(equals)
    if check.get("contains") is not None:
        return value is not None and check["contains"] in json.dumps(value)
    present = value not in (None, {}, [], "")
    return present if check.get("exists") is not False else not present


def _has_matcher(check: dict) -> bool:
    return any(k in check for k in ("equals", "contains", "regex")) or check.get("exists") is not None


def describe(check: dict) -> str:
    if check.get("regex") is not None:
        want = f"~ /{check['regex']}/"
    elif "equals" in check:
        want = f"== {check['equals']!r}"
    elif check.get("contains") is not None:
        want = f"contains {check['contains']!r}"
    else:
        want = "exists" if check.get("exists") is not False else "absent"
    if check.get("output"):
        return f"apply output {want}"
    if check.get("command"):
        return f"`{check['command'][:80]}` {want}"
    return f"{check.get('node')} {check.get('path')} {want}"


def run_check(check: dict, lab: str, apply_output: str, runner, sleep, poll_s: float) -> dict:
    deadline = time.monotonic() + float(check.get("wait_s") or 0)
    while True:
        if check.get("output"):
            value = apply_output
            ok = matches(check, value)
        elif check.get("command"):
            cmd = check["command"].replace("{lab}", lab)
            proc = runner(["sh", "-c", cmd], timeout=CHECK_TIMEOUT)
            value = proc.stdout or ""
            ok = proc.returncode == 0 and (not _has_matcher(check) or matches(check, value))
        else:
            return {"check": describe(check), "ok": False,
                    "detail": "node/path gets need the eval harness; write this check as a command"}
        if ok or time.monotonic() >= deadline:
            break
        sleep(poll_s)
    return {"check": describe(check), "ok": ok, "observed": str(value)[-400:]}


# ── run ─────────────────────────────────────────────────────────────────────

def _apply_cmd(apply: Path, inventory: "Path | None") -> "list[str]":
    if apply.suffix in (".yml", ".yaml"):
        cmd = ["ansible-playbook", str(apply)]
        return cmd + (["-i", str(inventory)] if inventory else [])
    if apply.suffix == ".py":
        return [sys.executable, str(apply)]
    return ["bash", str(apply)]


def _tail(proc) -> str:
    return ((proc.stdout or "") + (proc.stderr or ""))[-1500:]


def run(topology, apply=None, checks=None, out_dir=None, before=None, runner=default_runner,
        which=shutil.which, sleep=time.sleep, poll_s: float = 5.0, sudo: bool = False,
        inventory=None) -> dict:
    topology = Path(topology).resolve()
    report = {"topology": str(topology), "lab": "", "mode": "", "result": "", "validation": {},
              "preflight": {}, "deploy": None, "before": None, "apply": None, "checks": [],
              "teardown": None}
    out_dir = Path(out_dir) if out_dir else topology.parent / "lab-reports"

    v = validate_topology(topology)
    report["validation"], report["lab"] = v, v["name"] or topology.stem.split(".")[0]
    check_list = []
    try:
        check_list = load_checks(checks) if checks else []
    except (OSError, ValueError) as exc:
        v["ok"] = False
        v["errors"].append(f"checks: {exc}")
    report["checks_defined"] = len(check_list)
    if not v["ok"]:
        report["mode"], report["result"] = "validate-only", "invalid"
        return _write(report, out_dir)

    pf = preflight(runner, which)
    report["preflight"], report["mode"] = pf, pf["mode"]
    if pf["mode"] != "lab":
        report["result"] = "validate-only"
        if apply:
            report["apply"] = _validate_artifact(Path(apply))
        return _write(report, out_dir)

    clab = (["sudo"] if sudo else []) + [pf["containerlab"]]
    deploy_attempted = False
    try:
        deploy_attempted = True
        proc = runner(clab + ["deploy", "-t", str(topology), "--reconfigure"], timeout=CLAB_TIMEOUT)
        report["deploy"] = {"ok": proc.returncode == 0, "output": _tail(proc)}
        if proc.returncode != 0:
            report["result"] = "deploy-failed"
            return report
        if before:  # e.g. the pyATS pre-change snapshot, taken on the fresh lab
            proc = runner(["sh", "-c", before.replace("{lab}", report["lab"])], timeout=APPLY_TIMEOUT)
            report["before"] = {"ok": proc.returncode == 0, "output": _tail(proc)}
            if proc.returncode != 0:
                report["result"] = "before-failed"
                return report
        apply_out = ""
        if apply:
            inv = inventory or topology.parent / f"clab-{report['lab']}" / "ansible-inventory.yml"
            proc = runner(_apply_cmd(Path(apply).resolve(), Path(inv)), timeout=APPLY_TIMEOUT)
            apply_out = proc.stdout or ""
            report["apply"] = {"ok": proc.returncode == 0, "output": _tail(proc)}
            if proc.returncode != 0:
                report["result"] = "apply-failed"
                return report
        report["checks"] = [run_check(c, report["lab"], apply_out, runner, sleep, poll_s)
                            for c in check_list]
        report["result"] = "pass" if all(c["ok"] for c in report["checks"]) else "fail"
    except Exception as exc:
        report["result"], report["error"] = "error", f"{type(exc).__name__}: {exc}"
    finally:
        if deploy_attempted:
            proc = runner(clab + ["destroy", "-t", str(topology), "--cleanup"], timeout=CLAB_TIMEOUT)
            report["teardown"] = {"ok": proc.returncode == 0, "output": _tail(proc)}
        _write(report, out_dir)
    return report


def _validate_artifact(path: Path) -> dict:
    try:
        import validate
        res = validate.run(path, skill="lab-test-change")
        return {"ok": res.get("status") in ("pass", "warn"), "validated": res.get("status")}
    except Exception as exc:
        return {"ok": False, "validated": f"error ({exc})"}


# ── report ──────────────────────────────────────────────────────────────────

_HEADLINE = {
    "pass": "PASS — change applied in the lab and every check passed",
    "fail": "FAIL — change applied but checks failed",
    "apply-failed": "FAIL — the change did not apply cleanly",
    "deploy-failed": "FAIL — the lab did not deploy",
    "before-failed": "FAIL — the pre-change step (--before) failed",
    "error": "ERROR — the run stopped unexpectedly",
    "invalid": "INVALID — fix the topology or checks file first",
    "validate-only": "VALIDATE-ONLY — NOT lab-tested",
}


def to_markdown(r: dict) -> str:
    lines = [f"# Lab report: {r['lab']}", "", f"**{_HEADLINE.get(r['result'], r['result'])}**", "",
             f"- Mode: {r['mode']}", f"- Topology: `{r['topology']}`"]
    pf = r.get("preflight") or {}
    if r["mode"] == "validate-only" and pf.get("reason"):
        lines.append(f"- Why validate-only: {pf['reason']} — install docker + containerlab "
                     "to deploy the lab; nothing was deployed or applied.")
    for e in r["validation"].get("errors", []):
        lines.append(f"- Topology error: {e}")
    for step in ("deploy", "before", "apply"):
        if r.get(step) and "validated" in r[step]:
            lines.append(f"- Change: `damira validate` {r[step]['validated']} — not applied to a lab")
        elif r.get(step):
            lines.append(f"- {step.title()}: {'ok' if r[step].get('ok') else 'FAILED'}")
    if r["mode"] == "validate-only" and r.get("checks_defined"):
        lines.append(f"- Checks: {r['checks_defined']} defined, none run (no lab)")
    if r.get("error"):
        lines.append(f"- Error: {r['error']}")
    if r["checks"]:
        lines += ["", "| Check | Result |", "|---|---|"]
        lines += [f"| {c['check'].replace('|', '/')} | {'pass' if c['ok'] else 'FAIL'} |" for c in r["checks"]]
    if r.get("teardown") is not None:
        lines += ["", f"Teardown (containerlab destroy --cleanup): "
                      f"{'ok' if r['teardown']['ok'] else 'FAILED — run it by hand'}"]
    return "\n".join(lines) + "\n"


def _write(report: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"{report['lab']}-lab-report"
    Path(f"{stem}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    Path(f"{stem}.md").write_text(to_markdown(report), encoding="utf-8")
    report["report_paths"] = [f"{stem}.json", f"{stem}.md"]
    return report


# ── CLI ─────────────────────────────────────────────────────────────────────

def _sigterm(*_):
    raise KeyboardInterrupt  # unwinds through run()'s finally, so the lab is destroyed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="damira lab", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("preflight", help="docker + containerlab available? -> lab | validate-only")
    s = sub.add_parser("validate", help="topology sanity check (no docker)")
    s.add_argument("topology")
    s = sub.add_parser("run", help="deploy, apply, check, report, destroy")
    s.add_argument("topology")
    s.add_argument("--apply", help="playbook (.yml), script (.py) or shell (.sh) to apply")
    s.add_argument("--checks", help="<lab>.checks.json (harness StateCheck shape)")
    s.add_argument("--before", help="shell command run after deploy, before apply "
                                    "(e.g. the pyATS pre-change snapshot); {lab} expands")
    s.add_argument("--inventory", help="Ansible inventory (default: containerlab's generated one)")
    s.add_argument("--out-dir", help="report folder (default: lab-reports/ next to the topology)")
    s.add_argument("--sudo", action="store_true", help="run containerlab under sudo")
    a = p.parse_args(argv)

    if a.action == "preflight":
        print(json.dumps(preflight(), indent=2))
        return 0
    if a.action == "validate":
        res = validate_topology(a.topology)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    signal.signal(signal.SIGTERM, _sigterm)
    report = run(a.topology, apply=a.apply, checks=a.checks, out_dir=a.out_dir, before=a.before,
                 sudo=a.sudo, inventory=a.inventory)
    print(to_markdown(report))
    print("Report: " + " , ".join(report.get("report_paths", [])))
    return 0 if report["result"] in ("pass", "validate-only") else 1


if __name__ == "__main__":
    sys.exit(main())
