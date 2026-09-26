#!/usr/bin/env python3
"""`damira validate <path>` — deterministic checks on generated automation, run locally.

The host model writes the playbook, Terraform, script or config; this checks it before
anyone runs it. Nothing leaves the machine and no Damira API call is made.

Standard library first. Each external tool runs only if it is on PATH; otherwise the
check reports `skipped` with a one-line install hint.

  YAML       yamllint, else PyYAML parse if importable, else a stdlib tab check
  Ansible    ansible-playbook --syntax-check, ansible-lint --profile production --offline
  Terraform  terraform fmt -check; CLI mode only: init -backend=false + validate
  Python     ast.parse (always), ruff check
  Jinja2     sandboxed render with StrictUndefined, if jinja2 is importable
  Config     .cfg/.conf (and .txt under configs/) through audit_config.py

Two modes. `cli` is someone running `damira validate`. `hook` is the post-write hook
acting on a file the model just wrote, so everything it runs is treated as untrusted:
Jinja renders in a sandbox, Ansible checks an isolated copy with an empty ansible.cfg,
Terraform stops at `fmt -check` (init would fetch model-chosen modules and run provider
binaries), and the whole run fits a fixed time budget.

Overall status: fail if any check fails; unverified if nothing substantive ran (only
skipped or basic checks), which is never reported as a pass; warn if a check warned;
otherwise pass. Config
audits fail only on HIGH findings about lines that are present. "Something is missing"
findings (no enable secret, no NTP, ...) only warn, because generated files are often
snippets, not whole configs.

Every run appends one event to ~/.damira/logs/workflows.jsonl (see events.py): fixed
labels, rule IDs and statuses only, never file content, names or tool output.

Exit codes: 0 = no failures (pass, warn or unverified), 1 = at least one check failed, 2 = bad input.
"""

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import audit_config  # noqa: E402
import events  # noqa: E402

CLI_TOOL_TIMEOUT = 120
HOOK_TOOL_TIMEOUT = 25
HOOK_BUDGET = 60  # seconds for the whole hook run; the hook configs allow 90
DETAIL_LINES = 15
SKIP_DIRS = {".git", ".terraform", "__pycache__", ".venv", "node_modules", ".ansible"}
CONFIG_EXTS = {".cfg", ".conf"}
YAML_EXTS = {".yml", ".yaml"}
JINJA_EXTS = {".j2", ".jinja", ".jinja2"}

# The only `ext` values that may reach the event log. A suffix taken from a real path can
# be anything ("tfmod.acmebank-prod"), so it is mapped, never copied.
_EXT_LABEL = {".tf": ".tf", ".yml": ".yml", ".yaml": ".yml", ".py": ".py", ".j2": ".j2",
              ".jinja": ".j2", ".jinja2": ".j2", ".cfg": ".conf", ".conf": ".conf", ".txt": ".conf"}
_SAFE_RULE = re.compile(r"^[A-Za-z0-9_.\-\[\]]{1,48}$")

# Checks whose pass says little on its own; a run made only of these is "unverified".
_BASIC_CHECKS = {"yaml-basic"}
_NON_SUBSTANTIVE_RULES = {"audit/unsupported-vendor"}

HINTS = {
    "yamllint": "install with: pipx install yamllint",
    "ansible-playbook": "install with: pipx install --include-deps ansible",
    "ansible-lint": "install with: pipx install ansible-lint",
    "terraform": "install from https://developer.hashicorp.com/terraform/install",
    "ruff": "install with: pipx install ruff",
    "jinja2": "install with: pip install jinja2 (into the python3 that runs Damira)",
}

# Collection prefix → vendor label, for the event log.
_VENDOR_BY_COLLECTION = {
    "cisco.ios": "cisco_ios", "cisco.iosxr": "cisco_iosxr", "cisco.nxos": "cisco_nxos",
    "arista.eos": "arista_eos", "juniper.device": "juniper_junos", "junipernetworks.junos": "juniper_junos",
    "paloaltonetworks.panos": "panos", "fortinet.fortios": "fortios", "vyos.vyos": "vyos",
}
_VENDOR_BY_AUDIT = {"ios": "cisco_ios", "nxos": "cisco_nxos", "eos": "arista_eos", "junos": "juniper_junos"}

# yamllint's default 80-column error fails nearly every real playbook; this keeps the
# checks that catch broken YAML and drops the style nags.
_YAMLLINT_CONFIG = ("{extends: default, rules: {line-length: {max: 160}, document-start: disable, "
                    "truthy: {allowed-values: ['true', 'false', 'yes', 'no'], check-keys: false}, "
                    "comments: {min-spaces-from-content: 1}}}")


class _Ctx:
    """Per-run settings: mode and the deadline every external tool must fit inside."""

    def __init__(self, mode: str):
        self.mode = mode
        self.cap = HOOK_TOOL_TIMEOUT if mode == "hook" else CLI_TOOL_TIMEOUT
        self.deadline = time.monotonic() + HOOK_BUDGET if mode == "hook" else None

    def timeout(self) -> "float | None":
        if self.deadline is None:
            return float(self.cap)
        left = self.deadline - time.monotonic()
        return None if left < 2 else min(float(self.cap), left)


def _ext_label(path: Path, is_dir: bool = False) -> str:
    return "dir" if is_dir else _EXT_LABEL.get(path.suffix.lower(), "other")


def _rule(prefix: str, raw: str) -> str:
    """Rule IDs come from tool output; only a short, plain token may pass through."""
    raw = (raw or "").strip()
    return f"{prefix}/{raw}" if _SAFE_RULE.match(raw) else f"{prefix}/other"


def _check(name: str, path: Path, status: str, rule_ids=None, detail: str = "", hint: str = "",
           ext: str = "") -> dict:
    return {"check": name, "file": str(path), "ext": ext or _ext_label(path, path.is_dir()),
            "status": status, "rule_ids": sorted(set(rule_ids or [])), "detail": detail, "hint": hint}


def _skipped(name: str, path: Path, tool: str, ext: str = "") -> dict:
    return _check(name, path, "skipped", hint=f"{tool} not found — {HINTS[tool]}", ext=ext)


def _out_of_time(name: str, path: Path, ext: str = "") -> dict:
    return _check(name, path, "skipped", ext=ext,
                  hint="not run: the hook's time budget ran out — run `damira validate` on it directly")


def _run(ctx: _Ctx, cmd: "list[str]", cwd: "Path | None" = None,
         env: "dict | None" = None) -> "tuple[int | None, str]":
    """(returncode, output). returncode None means it did not finish (budget/timeout)."""
    timeout = ctx.timeout()
    if timeout is None:
        return None, "time budget exhausted"
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                              timeout=timeout, env={**os.environ, **(env or {})})
    except subprocess.TimeoutExpired:
        return None, f"timed out after {int(timeout)}s"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _tail(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[:DETAIL_LINES]) + ("\n…" if len(lines) > DETAIL_LINES else "")


# --- YAML / Ansible ---------------------------------------------------------------

_HOSTS_RE = re.compile(r"^-?\s*(?:-\s+)?hosts:\s*\S", re.MULTILINE)


def is_playbook(text: str) -> bool:
    """A YAML list whose plays have `hosts:`. PyYAML when available, regex otherwise."""
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        return isinstance(data, list) and any(isinstance(p, dict) and "hosts" in p for p in data)
    except ImportError:
        return bool(re.match(r"\s*(---\s*)?(#.*\n\s*)*-", text)) and bool(_HOSTS_RE.search(text))
    except Exception:  # noqa: BLE001 — unparseable: fall back to the textual hint
        return bool(_HOSTS_RE.search(text))


def check_yaml(ctx: _Ctx, path: Path, text: str) -> dict:
    if shutil.which("yamllint"):
        code, out = _run(ctx, ["yamllint", "-f", "parsable", "-d", _YAMLLINT_CONFIG, str(path)])
        if code is None:
            return _out_of_time("yamllint", path)
        rules = re.findall(r"\[error\] .*\(([\w-]+)\)$", out, re.MULTILINE)
        if "[error]" in out and not rules:
            rules = ["syntax"]
        status = "fail" if code == 1 else ("warn" if out else "pass")
        return _check("yamllint", path, status, [_rule("yamllint", r) for r in rules], _tail(out))
    try:
        import yaml  # type: ignore
    except ImportError:
        return _stdlib_yaml(path, text)
    try:
        yaml.safe_load(text)
        return _check("yaml-parse", path, "pass", hint=f"yamllint not found — {HINTS['yamllint']}")
    except yaml.YAMLError as exc:
        return _check("yaml-parse", path, "fail", ["yaml/syntax"], str(exc))


def _stdlib_yaml(path: Path, text: str) -> dict:
    """No yamllint, no PyYAML: catch the one error every YAML parser rejects. This is not
    validation — the run reports unverified unless something else ran."""
    for i, line in enumerate(text.splitlines(), 1):
        indent = line[: len(line) - len(line.lstrip())]
        if "\t" in indent:
            return _check("yaml-basic", path, "fail", ["yaml/tab-indent"],
                          f"line {i}: tab used for indentation — YAML forbids tabs")
    return _check("yaml-basic", path, "pass",
                  hint=f"YAML not parsed (no yamllint or PyYAML) — {HINTS['yamllint']}")


class _AnsibleSandbox:
    """Hook mode: check a lone copy of the playbook with an empty ansible.cfg.

    Ansible loads ansible.cfg from the working directory and plugin directories
    (`library/`, `*_plugins/`) next to the playbook, and plugins are Python. A model that
    can write the playbook can write those too, so the hook never runs Ansible in place.
    """

    def __init__(self, ctx: _Ctx, path: Path):
        self.ctx, self.path = ctx, path
        self._tmp = None

    def __enter__(self) -> "tuple[Path, Path, dict]":
        if self.ctx.mode != "hook":
            return self.path, self.path.parent, {}
        self._tmp = tempfile.TemporaryDirectory(prefix="damira-ansible-")
        root = Path(self._tmp.name)
        (root / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")
        work = root / "play"
        work.mkdir()
        copy = work / self.path.name
        shutil.copyfile(self.path, copy)
        return copy, work, {"ANSIBLE_CONFIG": str(root / "ansible.cfg")}

    def __exit__(self, *exc) -> None:
        if self._tmp:
            self._tmp.cleanup()


# Failures that only mean "an include/role/vars file wasn't copied into the sandbox".
_ISOLATION_MISSES = ("the role '", "was not found", "could not find or access", "unable to retrieve file")


def check_ansible_syntax(ctx: _Ctx, path: Path) -> dict:
    if not shutil.which("ansible-playbook"):
        return _skipped("ansible-syntax", path, "ansible-playbook")
    with _AnsibleSandbox(ctx, path) as (target, cwd, env):
        code, out = _run(ctx, ["ansible-playbook", "-i", "localhost,", "--syntax-check", str(target)],
                         cwd=cwd, env=env)
    if code is None:
        return _out_of_time("ansible-syntax", path)
    if code == 0:
        return _check("ansible-syntax", path, "pass")
    if ctx.mode == "hook" and any(m in out.lower() for m in _ISOLATION_MISSES):
        return _check("ansible-syntax", path, "warn", ["ansible-syntax/isolated"], _tail(out),
                      "roles/includes aren't available to the hook's isolated check — "
                      "run `damira validate` on the project directory")
    rule = "ansible-syntax/unresolved-module" if "couldn't resolve module" in out else "ansible-syntax/error"
    hint = ("fix the module name, or install its collection: ansible-galaxy collection install <ns.coll>"
            if rule.endswith("unresolved-module") else "")
    return _check("ansible-syntax", path, "fail", [rule], _tail(out), hint)


def _lint_line(issue: dict) -> str:
    loc = issue.get("location", {})
    line = (loc.get("lines") or {}).get("begin") or ((loc.get("positions") or {}).get("begin") or {}).get("line")
    return str(line or "?")


def check_ansible_lint(ctx: _Ctx, path: Path) -> dict:
    if not shutil.which("ansible-lint"):
        return _skipped("ansible-lint", path, "ansible-lint")
    with _AnsibleSandbox(ctx, path) as (target, cwd, env):
        code, out = _run(ctx, ["ansible-lint", "--offline", "--profile", "production", "--nocolor",
                               "-f", "codeclimate", str(target)], cwd=cwd, env=env)
    if code is None:
        return _out_of_time("ansible-lint", path)
    rules, detail = [], out
    try:
        start = out.index("[")
        issues = json.loads(out[start: out.rindex("]") + 1])
        rules = [i.get("check_name", "") for i in issues]
        detail = "\n".join(f"{_lint_line(i)}: {i.get('check_name')}: {i.get('description', '')}"
                           for i in issues)
    except ValueError:
        pass
    if code == 0:
        return _check("ansible-lint", path, "pass")
    return _check("ansible-lint", path, "fail",
                  [_rule("ansible-lint", r) for r in rules] or ["ansible-lint/error"], _tail(detail))


# --- Terraform ----------------------------------------------------------------------

# `terraform init` failing on these means the HCL is wrong, not the network.
_TF_SYNTAX_MARKERS = ("Argument or block definition required", "Invalid block definition",
                      "Unsupported block type", "Unsupported argument", "Invalid expression",
                      "Missing required argument", "Unclosed configuration block", "Invalid character")


def check_terraform(ctx: _Ctx, tf_dir: Path) -> "list[dict]":
    if not shutil.which("terraform"):
        return [_skipped("terraform-fmt", tf_dir, "terraform", ".tf"),
                _skipped("terraform-validate", tf_dir, "terraform", ".tf")]
    results = []
    # fmt -check only reads .tf files; it runs no providers and downloads nothing.
    code, out = _run(ctx, ["terraform", "fmt", "-check", "-list=true", "-no-color"], cwd=tf_dir)
    if code is None:
        results.append(_out_of_time("terraform-fmt", tf_dir, ".tf"))
    elif code == 0:
        results.append(_check("terraform-fmt", tf_dir, "pass", ext=".tf"))
    elif code == 3 or out and "Error" not in out:
        results.append(_check("terraform-fmt", tf_dir, "fail", ["terraform/fmt"],
                              "not canonically formatted (run `terraform fmt`):\n" + _tail(out), ext=".tf"))
    else:
        results.append(_check("terraform-fmt", tf_dir, "fail", ["terraform/syntax"], _tail(out), ext=".tf"))

    if ctx.mode == "hook":
        results.append(_check("terraform-validate", tf_dir, "skipped", ext=".tf", hint=(
            "not run from the hook: init downloads the modules and providers the file names and "
            f"runs provider binaries. Run `damira validate {tf_dir.name}` yourself to check it.")))
        return results
    results.append(_terraform_validate(ctx, tf_dir))
    return results


def _terraform_validate(ctx: _Ctx, tf_dir: Path) -> dict:
    """init -backend=false + validate on a copy, with TF_DATA_DIR in a temp dir, so nothing
    (.terraform/, lock file) is left in the user's folder and a failed init isn't sticky.
    Relative module sources that point outside the directory won't resolve in the copy."""
    with tempfile.TemporaryDirectory(prefix="damira-tf-") as tmp:
        work = Path(tmp) / "src"
        shutil.copytree(tf_dir, work, ignore=shutil.ignore_patterns(*SKIP_DIRS, ".terraform.lock.hcl"))
        env = {"TF_DATA_DIR": str(Path(tmp) / "data"), "TF_IN_AUTOMATION": "1"}
        code, out = _run(ctx, ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
                         cwd=work, env=env)
        if code is None:
            return _out_of_time("terraform-validate", tf_dir, ".tf")
        if code != 0:
            if any(m in out for m in _TF_SYNTAX_MARKERS):
                return _check("terraform-validate", tf_dir, "fail", ["terraform/syntax"], _tail(out),
                              "the configuration doesn't parse — fix the errors above", ext=".tf")
            return _check("terraform-validate", tf_dir, "fail", ["terraform/init"], _tail(out),
                          "terraform init failed — check the module and provider sources "
                          "(downloading them needs network access)", ext=".tf")
        code, out = _run(ctx, ["terraform", "validate", "-json", "-no-color"], cwd=work, env=env)
    if code is None:
        return _out_of_time("terraform-validate", tf_dir, ".tf")
    try:
        report = json.loads(out)
        diags = report.get("diagnostics", [])
        detail = "\n".join(f"{d.get('severity')}: {d.get('summary')} — {d.get('detail', '')}".strip()
                           for d in diags)
        valid = bool(report.get("valid"))
    except ValueError:
        detail, valid = out, code == 0
    return _check("terraform-validate", tf_dir, "pass" if valid else "fail",
                  [] if valid else ["terraform/validate"], _tail(detail), ext=".tf")


# --- Python / Jinja / config --------------------------------------------------------

def check_python(ctx: _Ctx, path: Path, text: str) -> "list[dict]":
    try:
        ast.parse(text, filename=str(path))
        results = [_check("python-ast", path, "pass")]
    except SyntaxError as exc:
        return [_check("python-ast", path, "fail", ["python/syntax"], f"line {exc.lineno}: {exc.msg}")]
    if not shutil.which("ruff"):
        results.append(_skipped("ruff", path, "ruff"))
        return results
    code, out = _run(ctx, ["ruff", "check", "--output-format", "json", "--no-cache", str(path)])
    if code is None:
        results.append(_out_of_time("ruff", path))
        return results
    try:
        issues = json.loads(out or "[]")
        rules = [_rule("ruff", i.get("code") or "error") for i in issues]
        detail = "\n".join(f"{i['location']['row']}: {i.get('code')} {i.get('message')}" for i in issues)
    except (ValueError, KeyError, TypeError):
        rules, detail = (["ruff/error"] if code else []), out
    results.append(_check("ruff", path, "fail" if code else "pass", rules, _tail(detail)))
    return results


def _vars_for(path: Path) -> "dict | None":
    """Variables for a template: <stem>.vars.yml or vars.yml beside it (needs PyYAML)."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    stem = path.name.split(".")[0]
    for name in (f"{stem}.vars.yml", f"{stem}.vars.yaml", "vars.yml", "vars.yaml"):
        candidate = path.parent / name
        if candidate.is_file():
            try:
                data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, yaml.YAMLError):
                return None
    return None


def check_jinja(path: Path, text: str) -> dict:
    """Always render in jinja2's SandboxedEnvironment: the template is model-written, and
    a plain Environment lets `{{ cycler.__init__.__globals__.os... }}` run Python."""
    try:
        import jinja2  # type: ignore
        from jinja2 import meta  # type: ignore
        from jinja2.sandbox import SandboxedEnvironment, SecurityError  # type: ignore
    except ImportError:
        return _skipped("jinja", path, "jinja2")
    strict = SandboxedEnvironment(undefined=jinja2.StrictUndefined)
    try:
        parsed = strict.parse(text)
    except jinja2.TemplateSyntaxError as exc:
        return _check("jinja", path, "fail", ["jinja/syntax"], f"line {exc.lineno}: {exc.message}")
    needed = sorted(meta.find_undeclared_variables(parsed))
    variables = _vars_for(path)
    # Without a vars file, still render (lenient undefined) so unsafe access is caught.
    env = strict if variables is not None else SandboxedEnvironment(undefined=jinja2.ChainableUndefined)
    try:
        env.from_string(text).render(**(variables or {}))
    except SecurityError as exc:
        return _check("jinja", path, "fail", ["jinja/sandbox-violation"],
                      f"template reaches Python internals, which is not allowed: {exc}")
    except jinja2.UndefinedError as exc:
        return _check("jinja", path, "fail", ["jinja/undefined-variable"], str(exc))
    except Exception as exc:  # noqa: BLE001 — a render error is a finding, not a crash
        return _check("jinja", path, "fail", ["jinja/render-error"], f"{type(exc).__name__}: {exc}")
    if variables is None and needed:
        return _check("jinja", path, "warn", ["jinja/unverified-vars"],
                      "no vars file found to render against; template needs: " + ", ".join(needed),
                      f"add {path.name.split('.')[0]}.vars.yml or vars.yml beside it to check them")
    return _check("jinja", path, "pass")


def check_config(path: Path, text: str) -> "tuple[dict, str]":
    vendor = audit_config.detect_vendor(text)
    if vendor not in audit_config.VENDORS:
        return _check("config-audit", path, "warn", ["audit/unsupported-vendor"],
                      audit_config.unsupported_message()), vendor
    findings = audit_config.audit_detailed(text, "all", vendor)
    # line 0 = "something is missing" from the whole config; a generated snippet is
    # expected to miss most of it, so those never fail the file on their own. A fragment
    # stamped by `damira render` is known to be partial: drop them so it can PASS.
    if audit_config.golden_fragment_vendor(text) == vendor:
        findings = [f for f in findings if f["line"]]
    failing = any(f["severity"] == "HIGH" and f["line"] for f in findings)
    status = "fail" if failing else ("warn" if findings else "pass")
    detail = "\n".join(f"[{f['severity']}] {f['rule_id']} "
                       f"{'line ' + str(f['line']) + ': ' if f['line'] else '(whole config) '}"
                       f"{f['message'].splitlines()[0]}" for f in findings)
    return _check("config-audit", path, status, [f["rule_id"] for f in findings], detail), vendor


# --- driver -------------------------------------------------------------------------

def _is_config(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in CONFIG_EXTS or (ext == ".txt" and "configs" in path.parts)


def _files(target: Path) -> "list[Path]":
    if target.is_file():
        return [target]
    out = []
    for root, dirs, files in os.walk(target):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        out.extend(Path(root) / f for f in sorted(files))
    return out


def _plugin_version() -> str:
    for manifest in (".claude-plugin/plugin.json", ".cursor-plugin/plugin.json"):
        try:
            return json.loads((_HERE.parent / manifest).read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            continue
    return "unknown"


def _overall(checks: "list[dict]") -> str:
    if not checks:
        return "empty"
    if any(c["status"] == "fail" for c in checks):
        return "fail"
    substantive = [c for c in checks if c["status"] in ("pass", "warn")
                   and c["check"] not in _BASIC_CHECKS
                   and not set(c["rule_ids"]) & _NON_SUBSTANTIVE_RULES]
    if not substantive:
        return "unverified"
    return "warn" if any(c["status"] == "warn" for c in substantive) else "pass"


def run(target, host: str = "cli", skill: str = "", mode: str = "cli", session_id=None,
        model=None, input_tokens=None, output_tokens=None, cache_read: int = 0,
        cache_write: int = 0) -> dict:
    """Validate a file or directory. Returns the full result (paths and detail included);
    the logged event is a scrubbed subset. mode: "cli" or "hook" (see module docstring).

    session_id groups repeated validations of one file into a generate-validate loop
    (#475); it is hashed with a local salt and never logged. model and token counts are
    whatever the host reported, or None."""
    started = time.monotonic()
    ctx = _Ctx("hook" if mode == "hook" else "cli")
    target = Path(target).expanduser().resolve()
    checks: "list[dict]" = []
    frameworks: "list[str]" = []
    vendors: "list[str]" = []
    tf_dirs: "list[Path]" = []

    for path in _files(target):
        ext = path.suffix.lower()
        if ext == ".tf":
            if path.parent not in tf_dirs:
                tf_dirs.append(path.parent)
            continue
        if ext not in YAML_EXTS | JINJA_EXTS | {".py"} and not _is_config(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            checks.append(_check("read", path, "fail", ["io/unreadable"], str(exc)))
            continue
        if ext in YAML_EXTS:
            checks.append(check_yaml(ctx, path, text))
            if is_playbook(text):
                frameworks.append("ansible")
                vendors += [v for k, v in _VENDOR_BY_COLLECTION.items() if re.search(rf"\b{re.escape(k)}\.", text)]
                checks.append(check_ansible_syntax(ctx, path))
                checks.append(check_ansible_lint(ctx, path))
            else:
                frameworks.append("yaml")
        elif ext == ".py":
            frameworks.append("python")
            checks += check_python(ctx, path, text)
        elif ext in JINJA_EXTS:
            frameworks.append("jinja")
            checks.append(check_jinja(path, text))
        else:
            frameworks.append("config")
            result, vendor = check_config(path, text)
            checks.append(result)
            vendors.append(_VENDOR_BY_AUDIT.get(vendor, "unknown"))

    for tf_dir in tf_dirs:
        frameworks.append("terraform")
        checks += check_terraform(ctx, tf_dir)

    status = _overall(checks)
    uniq = lambda xs: sorted(set(xs))  # noqa: E731
    result = {
        "run_id": str(uuid.uuid4()),
        "target": str(target),
        "mode": ctx.mode,
        "status": status,
        "framework": (uniq(frameworks)[0] if len(set(frameworks)) == 1 else
                      ("mixed" if frameworks else "none")),
        "vendor": (uniq(vendors)[0] if len(set(vendors)) == 1 else ("mixed" if vendors else "")),
        "checks": checks,
        "counts": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "fail", "warn", "skipped")},
    }

    duration_ms = int((time.monotonic() - started) * 1000)
    session = session_id or os.environ.get("DAMIRA_SESSION_ID") or ""
    events.emit({
        **events.loop_fields(target, session, status, duration_ms),
        **events.model_fields(model, input_tokens, output_tokens, cache_read, cache_write),
        "event": "validate",
        "run_id": result["run_id"],
        "skill": skill if re.match(r"^[a-z0-9-]{1,40}$", skill or "") else "",
        "framework": result["framework"],
        "vendor": result["vendor"],
        "host": host if host in ("cli", "claude-code", "cursor") else "other",
        "plugin_version": _plugin_version(),
        "status": status,
        "duration_ms": duration_ms,
        "counts": result["counts"],
        "file_types": uniq(c["ext"] for c in checks),
        "checks": [{"check": c["check"], "ext": c["ext"], "status": c["status"], "rule_ids": c["rule_ids"]}
                   for c in checks],
    })
    events.flush()  # no-op unless the user opted in; never raises
    return result


def format_human(result: dict, base: "Path | None" = None) -> str:
    base = base or Path.cwd()
    mark = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skipped": "SKIP"}
    lines = []
    for c in result["checks"]:
        try:
            shown = os.path.relpath(c["file"], base)
        except ValueError:
            shown = c["file"]
        if shown.startswith(".."):
            shown = c["file"]
        lines.append(f"[{mark[c['status']]}] {c['check']:<18} {shown}")
        if c["detail"] and c["status"] in ("fail", "warn"):
            lines.extend("       " + ln for ln in c["detail"].splitlines())
        if c["hint"] and c["status"] in ("skipped", "fail", "warn"):
            lines.append(f"       hint: {c['hint']}")
    n = result["counts"]
    if result["status"] == "empty":
        lines.append("Nothing to validate (no .yml/.yaml, .tf, .py, .j2 or config files found).")
    elif result["status"] == "unverified":
        lines.append(f"\nvalidate: UNVERIFIED — the file was NOT validated: no real check could run "
                     f"({n['skipped']} skipped). Install the tools named in the hints above.")
    else:
        lines.append(f"\nvalidate: {result['status'].upper()} — {n['pass']} passed, {n['fail']} failed, "
                     f"{n['warn']} warnings, {n['skipped']} skipped")
    return "\n".join(lines)


def build_parser(p: "argparse.ArgumentParser | None" = None) -> argparse.ArgumentParser:
    p = p or argparse.ArgumentParser(prog="damira validate", description=__doc__.splitlines()[0])
    p.add_argument("path", help="file or directory to validate")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--host", default=os.environ.get("DAMIRA_HOST", "cli"),
                   choices=["cli", "claude-code", "cursor"], help=argparse.SUPPRESS)
    p.add_argument("--skill", default="", help=argparse.SUPPRESS)
    return p


def main_with_args(a) -> int:
    target = Path(a.path).expanduser()
    if not target.exists():
        print(f"damira validate: no such file or directory: {a.path}", file=sys.stderr)
        return 2
    result = run(target, host=a.host, skill=a.skill, mode="cli")
    print(json.dumps(result, indent=2) if a.json else format_human(result))
    return 1 if result["status"] == "fail" else 0


def main() -> None:
    sys.exit(main_with_args(build_parser().parse_args()))


if __name__ == "__main__":
    main()
