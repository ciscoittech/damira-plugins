#!/usr/bin/env python3
"""`damira render <task> --platform <p> --vars vars.yml [-o file]` — golden config templates.

Deterministic, reviewed baselines (NTP, AAA/TACACS+, SNMPv3, syslog, banner) for Cisco IOS,
NX-OS, Arista EOS and Junos, so the model does not hand-write lines that have one right
answer. Renders locally; no API call.

Templates live in templates/golden/<platform>/<task>.j2 with one example vars file per task
in templates/golden/examples/. Rendering uses jinja2's SandboxedEnvironment with
StrictUndefined: a missing variable is an error, never an empty line.

Secrets stay out of vars files: a value written as "env:NAME" is read from the environment
at render time, and rendering fails if NAME is unset. Only NET_/TACACS_/RADIUS_/SNMP_/
NTP_/SYSLOG_/GOLDEN_ names are readable, so a vars file from an untrusted repo cannot pull
API keys into the output. On stdout secrets are masked (<NAME>) unless --secrets says
otherwise; -o writes real values to a new 0600 file. --secrets ansible emits
{{ lookup('env', 'NAME') }} so a playbook resolves them at run time instead.

Values are data, and are checked before rendering: no control characters or quotes in any
value, plain tokens (addresses, names, interfaces) where a field is a token, and banner text
that cannot close its own delimiter. A value that could add a device command is an error.

jinja2 (and PyYAML for .yml vars) are optional dependencies, imported only here.
Exit codes: 0 = rendered, 1 = render failed or jinja2 missing, 2 = bad input.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "golden"
EXAMPLES_DIR = TEMPLATE_DIR / "examples"
_NAME = re.compile(r"^[a-z0-9_]{1,40}$")
_ENV_REF = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")
_ENV_ALLOWED = re.compile(r"^(NET|TACACS|RADIUS|SNMP|NTP|SYSLOG|GOLDEN)_[A-Z0-9_]+$")
SECRET_MODES = ("resolve", "mask", "ansible")
# Free text sits inside quotes (Junos) or at the end of a line; everything else is one token.
_FREE_TEXT = {"key", "auth_pass", "priv_pass", "location", "contact"}
_TOKEN = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,128}$")
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f\u2028\u2029]")
# With --secrets ansible the lines land in a *_config task, which Ansible templates:
# a value carrying jinja delimiters would run on the control node.
_JINJA = re.compile(r"\{[{%#]")
_ANSIBLE_LOOKUP = re.compile(r"\{\{ lookup\('env', '[A-Za-z_][A-Za-z0-9_]*'\) \}\}")
INSTALL_HINT = "install with: pip install jinja2 pyyaml (into the python3 that runs Damira)"


class GoldenError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def catalog() -> "list[tuple[str, str]]":
    """(task, platform) pairs that have a template."""
    return sorted((t.stem, t.parent.name) for t in TEMPLATE_DIR.glob("*/*.j2"))


def example_vars(task: str) -> Path:
    return EXAMPLES_DIR / f"{_checked(task, 'task')}.vars.yml"


def _checked(value: str, label: str) -> str:
    # Names become path segments; anything but a plain token could escape TEMPLATE_DIR.
    if not _NAME.match(value or ""):
        raise GoldenError(f"invalid {label} name: {value!r}")
    return value


def _resolve_env(value, secrets: str, used: list):
    if isinstance(value, dict):
        return {k: _resolve_env(v, secrets, used) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v, secrets, used) for v in value]
    if isinstance(value, str):
        m = _ENV_REF.match(value)
        if not m and _JINJA.search(value):
            raise GoldenError("values must not contain '{{', '{%' or '{#' — Ansible would template them")
        if m:
            name = m.group(1)
            if not _ENV_ALLOWED.match(name):
                raise GoldenError(f"env:{name} is not readable from a vars file — use a NET_, TACACS_, "
                                  "RADIUS_, SNMP_, NTP_, SYSLOG_ or GOLDEN_ variable")
            used.append(name)
            if secrets == "mask":
                return f"<{name}>"
            if secrets == "ansible":
                return "{{ lookup('env', '" + name + "') }}"
            if name not in os.environ:
                raise GoldenError(f"vars reference env:{name} but it is not set", 2)
            return os.environ[name]
    return value


def load_vars(path, secrets: str = "resolve", used: "list | None" = None) -> dict:
    """Read a vars file. `used` collects the env names referenced (for the caller's notice)."""
    path = Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GoldenError(f"cannot read vars file: {exc}") from exc
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise GoldenError(f"vars file is not valid JSON: {exc}") from exc
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise GoldenError(f"PyYAML is needed for .yml vars files — {INSTALL_HINT} "
                              "(or pass a .json vars file)", 1) from exc
        try:
            # Anchors/aliases buy nothing in a vars file and allow recursive or
            # exponential ("billion laughs") documents, so refuse them outright.
            if any(isinstance(ev, yaml.AliasEvent) for ev in yaml.parse(text, Loader=yaml.SafeLoader)):
                raise GoldenError("vars file must not use YAML anchors/aliases (&name / *name)")
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            where = getattr(exc, "problem_mark", None)
            at = f" at line {where.line + 1}, column {where.column + 1}" if where else ""
            problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
            raise GoldenError(f"vars file is not valid YAML{at}: {problem}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise GoldenError("vars file must be a mapping of name: value")
    return _resolve_env(data, secrets, used if used is not None else [])


def check_values(variables: dict) -> None:
    """Reject any value that could end a line, a quoted string or a banner early."""
    def walk(value, field: str):
        if isinstance(value, dict):
            for k, v in value.items():
                if not isinstance(k, str) or not _TOKEN.match(k):
                    raise GoldenError(f"invalid vars key {k!r}")
                walk(v, k)
            return
        if isinstance(value, list):
            for v in value:
                walk(v, field)
            return
        if isinstance(value, bool) or value is None:
            raise GoldenError(f"{field}: expected a value, got {value!r}")
        text = str(value)
        if _JINJA.search(text) and not _ANSIBLE_LOOKUP.fullmatch(text):
            raise GoldenError(f"{field}: '{{{{', '{{%' and '{{#' are not allowed in a value")
        if field == "text":
            if _CONTROL.search(text.replace("\n", "")) or "\\" in text or "^" in text \
                    or any(line.strip() == "EOF" for line in text.splitlines()):
                raise GoldenError("banner text must not contain '^', a backslash, a line reading "
                                  "EOF, or control characters — any of these can end the banner early")
            return
        if _CONTROL.search(text) or '"' in text or "\\" in text:
            raise GoldenError(f"{field}: newlines, control characters, quotes and backslashes are "
                              "not allowed in a value")
        # The value may have come from an env: secret, so never echo it back.
        if field not in _FREE_TEXT and not _TOKEN.match(text):
            raise GoldenError(f"{field}: value is not a plain token (address, name or interface)")
    walk(variables, "")


def render(task: str, platform: str, variables: dict) -> str:
    template = TEMPLATE_DIR / _checked(platform, "platform") / f"{_checked(task, 'task')}.j2"
    if not template.is_file():
        available = ", ".join(f"{t}/{p}" for t, p in catalog())
        raise GoldenError(f"no golden template for {task} on {platform}. Available: {available}")
    try:
        import jinja2  # type: ignore
        from jinja2.sandbox import SandboxedEnvironment  # type: ignore
    except ImportError as exc:
        raise GoldenError(f"jinja2 not found — {INSTALL_HINT}", 1) from exc
    check_values(variables)
    env = SandboxedEnvironment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
                               undefined=jinja2.StrictUndefined, trim_blocks=True,
                               lstrip_blocks=True, keep_trailing_newline=True, autoescape=False)
    try:
        return env.get_template(f"{platform}/{task}.j2").render(**variables)
    except jinja2.UndefinedError as exc:
        raise GoldenError(f"render failed: undefined variable — {exc}. "
                          f"See {example_vars(task)} for the expected vars.", 1) from exc
    except jinja2.TemplateError as exc:
        raise GoldenError(f"render failed: {exc}", 1) from exc


def main_with_args(a) -> int:
    try:
        if a.list or not a.task:
            for task, platform in catalog():
                print(f"{task:<12} {platform}")
            return 0
        if not a.platform:
            raise GoldenError("--platform is required")
        # Real secret values go only into a private file, never to stdout by default.
        secrets = getattr(a, "secrets", None) or ("resolve" if a.output else "mask")
        used: list = []
        variables = load_vars(a.vars or example_vars(a.task), secrets, used)
        text = render(a.task, a.platform, variables)
        if not a.output:
            sys.stdout.write(text)
            if used and secrets == "mask":
                print(f"damira render: masked {', '.join(sorted(set(used)))} — write real values with "
                      "-o <file>, or use --secrets ansible for playbook lookups", file=sys.stderr)
            return 0
        out = _write_private(Path(a.output).expanduser(), text, a.force)
    except GoldenError as exc:
        print(f"damira render: {exc}", file=sys.stderr)
        return exc.code
    print(f"wrote {out}\nnext: damira validate {out}")
    return 0


def _write_private(out: Path, text: str, force: bool) -> Path:
    """Create `out` 0600 without following a symlink (the output may hold resolved secrets)."""
    if out.is_symlink():
        raise GoldenError(f"{out} is a symlink — refusing to write through it")
    if out.exists():
        if not force:
            raise GoldenError(f"{out} exists (use --force to overwrite)")
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(out, flags, 0o600)
    except OSError as exc:
        raise GoldenError(f"cannot write {out}: {exc}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return out


def add_arguments(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("task", nargs="?", help="ntp, aaa_tacacs, snmpv3, syslog, banner")
    p.add_argument("--platform", help="cisco_ios, cisco_nxos, arista_eos, juniper_junos")
    p.add_argument("--vars", help="YAML/JSON vars file (default: the task's example vars)")
    p.add_argument("-o", "--output", help="write here instead of stdout, e.g. configs/rtr1-ntp.cfg")
    p.add_argument("--force", action="store_true", help="overwrite --output if it exists")
    p.add_argument("--secrets", choices=SECRET_MODES,
                   help="env: values — resolve (default with -o), mask (default on stdout), "
                        "or ansible lookups")
    p.add_argument("--list", action="store_true", help="list available templates")
    return p


if __name__ == "__main__":
    parser = add_arguments(argparse.ArgumentParser(prog="damira render", description=__doc__.splitlines()[0]))
    sys.exit(main_with_args(parser.parse_args()))
