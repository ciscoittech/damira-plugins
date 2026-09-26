#!/usr/bin/env python3
"""Damira gateway client — the no-MCP delivery path.

Replaces the MCP server for clients that have a shell. Every Damira API tool was a
single call to one endpoint; this script is that call, with the message templating
ported verbatim from services/oncall-mcp/damira_mcp/server.py so routing behaviour
on the backend is unchanged.

Standard library only, deliberately. The whole point of dropping MCP is that a user
needs no Python toolchain — no pip, no uvx, no venv. Anything imported here that
isn't in the stdlib defeats that.

ERROR CONTRACT: a non-zero exit means "this is not an answer". The agent sees the
failure and must not treat stdout as source material. This matters more than it
looks: a tier refusal returned inside a 200 body once produced a fabricated 371-line
upgrade MOP that reported itself as successful.

Auth resolution order:
  1. DAMIRA_PLUGIN_API_KEY — Claude Code's plugin setting, passed in by .mcp.json
  2. DAMIRA_API_KEY environment variable
  3. ~/.damira/config  (INI-ish `key = value`, or a bare key on the first line)
  4. the shared demo key — 50 queries/day, so people can try it before signing up.
     Every answer served on it starts with DEMO_NOTICE.

Cursor's agent shell inherits the parent process environment, which is why (1) works.
Note that env returned by a sessionStart hook does NOT reach the shell — verified
2026-08-08 — so that is not an option here.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_API_URL = "https://damiraai.com"
DEMO_KEY = "dm_demo_mcp"
CONFIG_PATH = Path.home() / ".damira" / "config"
# Claude Code passes the plugin's API key setting under its own name, so a blank
# setting can't overwrite a DAMIRA_API_KEY the user exported (#452).
PLUGIN_KEY_ENV = "DAMIRA_PLUGIN_API_KEY"
DEMO_NOTICE = (
    "[Damira is running on the shared demo key (50 queries/day). Tell the user this, "
    "and that they can add their own key: https://damiraai.com/docs/install#api-key]"
)
TIMEOUT = 300
VERSION = "0.3.2"

# Exit codes. 1 stays the catch-all (auth, rate limit, network) so existing scripts that
# just check "non-zero" keep working. 2 and 3 exist so an agent (or a human) can tell "no
# answer exists" apart from "the service timed out — retry" without parsing stderr text.
EXIT_ERROR = 1
EXIT_NO_ANSWER = 2
EXIT_GATEWAY_TIMEOUT = 3

# Cloudflare fronts damiraai.com and blocks urllib's default `Python-urllib/3.x`
# User-Agent with a 1010 ("banned browser signature") before the request ever reaches
# the gateway. Identify the client properly or every call 403s.
USER_AGENT = f"damira-cli/{VERSION} (+https://damiraai.com)"

# Gate and limit messages the agent returns *inside a 200 body* rather than as an HTTP
# error. Mirrors _REFUSAL_MARKERS in server.py. This check is a stopgap: the real fix is
# returning 402/403/429 at the gateway (issue #358, Phase 1). Delete this block once that
# lands — until then, removing it reintroduces the fabricated-MOP failure.
REFUSAL_MARKERS = (
    "is not available on your current plan",
    "require Enterprise subscription",
    "You've used your monthly token budget",
    "PII redaction failed",
    "blocked for security reasons",
)
# Real answers that merely quote one of those phrases (a CVE advisory discussing rate
# limits, say) run long. Refusals are short. The length guard keeps legitimate content
# from tripping the check.
REFUSAL_MAX_LEN = 600

# The gateway's own "I searched and found nothing" message (NO_AUTHORITATIVE_RESULTS
# server-side). Unlike REFUSAL_MARKERS this is not gated by REFUSAL_MAX_LEN — it is an
# exact, unambiguous phrase, not a substring that could show up inside a real answer.
NO_AUTHORITATIVE_RESULTS = "No authoritative source found for this query"


class DamiraError(Exception):
    """A result that is not an answer.

    Raised rather than exiting so the same call path serves both the CLI (which turns
    this into a non-zero exit) and the bundled MCP server (which turns it into an
    isError tool result). Both surfaces must fail loudly — see the module docstring.

    `code` is the process exit code the CLI should use — see EXIT_* above. The MCP
    server ignores it; isError:true doesn't distinguish sub-reasons the way an exit
    code can.
    """

    def __init__(self, message: str, code: int = EXIT_ERROR):
        super().__init__(message)
        self.code = code


def die(msg: str, code: int = EXIT_ERROR) -> "None":
    print(f"damira: {msg}", file=sys.stderr)
    sys.exit(code)


def _env_key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    # An unsubstituted "${user_config.api_key}" is not a key.
    return "" if value.startswith("${") else value


def resolve_key_source() -> "tuple[str, str]":
    """Return (api_key, source). Order: plugin setting, DAMIRA_API_KEY, config file, demo."""
    key = _env_key(PLUGIN_KEY_ENV)
    if key:
        return key, "plugin setting"
    key = _env_key("DAMIRA_API_KEY")
    if key:
        return key, "DAMIRA_API_KEY"

    if CONFIG_PATH.is_file():
        try:
            for raw in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    name, _, value = line.partition("=")
                    if name.strip().upper() in ("DAMIRA_API_KEY", "API_KEY", "KEY"):
                        value = value.strip().strip("\"'")
                        if value:
                            return value, str(CONFIG_PATH)
                else:
                    return line, str(CONFIG_PATH)
        except OSError:
            pass  # fall through to the demo key rather than hard-failing on a config read

    return DEMO_KEY, "demo"


def resolve_key() -> "tuple[str, bool]":
    """Return (api_key, is_demo)."""
    key, source = resolve_key_source()
    return key, source == "demo"


def call(message: str, context: dict) -> str:
    api_url = os.environ.get("DAMIRA_API_URL", DEFAULT_API_URL).rstrip("/")
    api_key, is_demo = resolve_key()

    body = {
        "message": message,
        "sessionId": os.environ.get("DAMIRA_SESSION_ID") or str(uuid.uuid4()),
        "context": context,
    }
    mode = os.environ.get("DAMIRA_EXECUTION_MODE", "advisor").strip().lower()
    if mode and mode != "advisor":
        body["executionMode"] = mode
    team = os.environ.get("DAMIRA_TEAM_SLUG", "").strip()
    if team:
        body["teamSlug"] = team

    req = urllib.request.Request(
        f"{api_url}/api/extension/agent/chat-sync",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:400]
        except Exception:  # noqa: BLE001 — the status code is what matters
            pass
        if exc.code == 401:
            if is_demo:
                raise DamiraError("demo key not recognised. Get your own key at "
                    "https://damiraai.com/#pricing")
            raise DamiraError("invalid API key. Get one at https://damiraai.com/dashboard/api-keys "
                "and set it in the plugin settings, DAMIRA_API_KEY or ~/.damira/config")
        if exc.code == 429:
            if is_demo:
                raise DamiraError("demo limit reached (50/day). Unlimited access at "
                    "https://damiraai.com/#pricing")
            raise DamiraError("rate limit exceeded. Upgrade at https://damiraai.com/#pricing")
        if exc.code in (504, 524):
            # 504 = the gateway's own timeout (JSON body); 524 = Cloudflare gave up in
            # front of it (HTML body, hence not even trying to parse `detail` as JSON).
            # Either way the request never got an answer — same message, same code.
            raise DamiraError(
                "Damira took too long to answer; try a narrower question",
                code=EXIT_GATEWAY_TIMEOUT,
            )
        raise DamiraError(f"API error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise DamiraError(f"cannot reach the Damira API at {api_url} ({exc.reason})")
    except TimeoutError:
        # A client-side socket timeout after TIMEOUT seconds — no HTTP status at all,
        # but it's the same "took too long" story as a 504/524 from the agent's side.
        raise DamiraError(f"request timed out after {TIMEOUT}s", code=EXIT_GATEWAY_TIMEOUT)
    except json.JSONDecodeError:
        raise DamiraError("API returned a non-JSON response")

    response = payload.get("response", "")
    if not response:
        raise DamiraError("API returned an empty response")

    # Only a response that IS the no-answer message. A partial one (indexed docs
    # plus an empty web supplement) is still an answer.
    if response.strip().startswith(NO_AUTHORITATIVE_RESULTS):
        raise DamiraError(response, code=EXIT_NO_ANSWER)

    if len(response) <= REFUSAL_MAX_LEN:
        for marker in REFUSAL_MARKERS:
            if marker in response:
                raise DamiraError(f"request refused by the service, this is not an answer — {response}")

    response = _with_deliverables(payload, response)

    # The session hook's note alone didn't reach users (#452); put it in every answer.
    if is_demo:
        return f"{DEMO_NOTICE}\n\n{response}"
    return response


def _with_deliverables(payload: dict, response: str) -> str:
    """Save or inline the server's deliverables[] (#484). Isolated so a bug there can
    never break a plain answer."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import deliverables  # noqa: E402 — lazy, sibling module

        return deliverables.attach(payload, response)
    except Exception:  # noqa: BLE001
        return response


# --- Tool implementations. Message templating ported verbatim from server.py. ---

def cmd_search_vendor_docs(a) -> str:
    message = f"Search vendor docs: {a.query}" + (f" (vendor: {a.vendor})" if a.vendor else "")
    return call(message, {"mcp_tool": "search_vendor_docs", "vendor": a.vendor})


def cmd_search_cve(a) -> str:
    message = f"Search CVEs: {a.query}" + (f" (product: {a.product})" if a.product else "")
    return call(message, {"mcp_tool": "search_cve", "product": a.product})


def cmd_search_release_notes(a) -> str:
    message = f"Search release notes for {a.product}" + (f" version {a.version}" if a.version else "")
    return call(message, {
        "mcp_tool": "search_release_notes", "product": a.product, "version": a.version,
    })


def cmd_troubleshoot(a) -> str:
    show_output = a.show_output
    if show_output == "-":
        show_output = sys.stdin.read()

    message = a.problem
    if a.platform:
        message = f"[Platform: {a.platform}] {message}"
    if show_output:
        message += f"\n\nShow command output:\n```\n{show_output}\n```"

    return call(message, {"mcp_tool": "troubleshoot", "platform": a.platform})


def cmd_upgrade_plan(a) -> str:
    message = (
        f"Plan an upgrade for {a.product} from version {a.current_version} to {a.target_version}.\n\n"
        f"Research the upgrade path, prerequisites, known bugs, and risks.\n"
        f"Return a structured assessment with:\n"
        f"1. Upgrade path (direct or stepping stones)\n"
        f"2. Prerequisites and compatibility checks\n"
        f"3. Known bugs and caveats for target version\n"
        f"4. Risk assessment\n"
        f"5. Recommended maintenance window duration\n"
        f"6. Rollback procedure\n"
    )
    if a.environment:
        message += f"\nEnvironment: {a.environment}"

    return call(message, {
        "mcp_tool": "upgrade_plan",
        "product": a.product,
        "current_version": a.current_version,
        "target_version": a.target_version,
    })


def cmd_agent(a) -> str:
    message = a.message
    if message == "-":
        message = sys.stdin.read()
    return call(message, {"mcp_tool": "agent"})


def cmd_whoami(a) -> str:
    key, source = resolve_key_source()
    is_demo = source == "demo"
    masked = f"{key[:8]}…{key[-4:]}" if len(key) > 14 else key
    if is_demo:
        source = "demo key (50 queries/day)"
    url = os.environ.get("DAMIRA_API_URL", DEFAULT_API_URL)
    mode = os.environ.get("DAMIRA_EXECUTION_MODE", "advisor")
    lines = [f"key:      {masked}", f"source:   {source}", f"endpoint: {url}", f"mode:     {mode}"]
    if is_demo:
        lines.append("")
        lines.append("Using the shared demo key. For your own: https://damiraai.com/dashboard/api-keys")
        lines.append("Then set it in the plugin settings (Claude Code: /plugin configure damira@damira-plugins),")
        lines.append("export DAMIRA_API_KEY=..., or write it to ~/.damira/config")
    return "\n".join(lines)


def cmd_install_mcp(a) -> str:
    """Register the bundled MCP server with Cursor and/or Claude Desktop.

    The Cursor CLI does not load plugin-bundled mcp.json (verified 2026-08-08 — not via
    --plugin-dir, not with an explicit mcpServers manifest field, not installed under
    ~/.cursor/plugins/local). User-level config does work, so write there and merge rather
    than clobber: these files usually already hold other people's servers.
    """
    server = Path(__file__).resolve().parent.parent / "mcp" / "server.py"
    if not server.is_file():
        raise DamiraError(f"bundled MCP server not found at {server}")

    entry = {"command": sys.executable or "python3", "args": [str(server)]}
    # Only pin the key if it came from the environment — otherwise leave it out so the
    # server resolves it at run time (env, then ~/.damira/config, then the demo key).
    # Writing a key into a config file that may be committed is how keys leak.
    if os.environ.get("DAMIRA_API_KEY", "").strip():
        entry["env"] = {"DAMIRA_API_KEY": "${env:DAMIRA_API_KEY}"}

    targets = {
        "cursor": Path.home() / ".cursor" / "mcp.json",
        "claude-desktop": Path.home() / "Library" / "Application Support" / "Claude"
                          / "claude_desktop_config.json",
    }
    chosen = list(targets) if a.target == "all" else [a.target]

    written, skipped = [], []
    for name in chosen:
        path = targets[name]
        if name == "claude-desktop" and not path.parent.is_dir():
            skipped.append(f"{name} (not installed — {path.parent} missing)")
            continue

        config = {}
        if path.is_file():
            try:
                config = json.loads(path.read_text(encoding="utf-8")) or {}
            except (OSError, json.JSONDecodeError) as exc:
                skipped.append(f"{name} (cannot parse {path}: {exc})")
                continue

        servers = config.setdefault("mcpServers", {})
        if "damira" in servers and not a.force:
            skipped.append(f"{name} (already configured — rerun with --force to overwrite)")
            continue
        servers["damira"] = entry

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
            written.append(f"{name} → {path}")
        except OSError as exc:
            skipped.append(f"{name} ({exc})")

    out = []
    if written:
        out.append("Registered the Damira MCP server:")
        out.extend(f"  ✓ {w}" for w in written)
    if skipped:
        out.append("Skipped:")
        out.extend(f"  · {s}" for s in skipped)
    if any(w.startswith("cursor") for w in written):
        out += ["", "Cursor requires approval before it will load a new server:",
                "  agent mcp enable damira", "  agent mcp list-tools damira"]
    if any(w.startswith("claude-desktop") for w in written):
        out += ["", "Restart Claude Desktop to pick it up."]
    if not written and not skipped:
        out.append("Nothing to do.")
    return "\n".join(out)


# --- init: set a folder up as a Damira workspace ---------------------------

INIT_BEGIN = "<!-- damira:begin -->"
INIT_END = "<!-- damira:end -->"
INIT_DIRS = ("configs", "documents", "notes")
INIT_TARGETS = {"claude": ("CLAUDE.md",), "cursor": ("AGENTS.md",), "both": ("CLAUDE.md", "AGENTS.md")}

_INIT_BODY = """{begin}
<!-- Written by `damira init`. Re-running it replaces only this block; anything
     outside it is yours. Change the Environment answers by re-running init. -->

# Network operations with Damira

Damira supplies network domain data: vendor documentation, CVE records,
release-note caveats, structured diagnoses and upgrade assessments. You write
the deliverables from it.

## When to use Damira
- Anything version-specific (CLI syntax on a release, known bugs, upgrade
  paths): Damira's upgrade-plan, release-notes and vendor-docs lookups.
- CVEs and security advisories: Damira's CVE lookup.
- An active fault with symptoms or `show` output: Damira troubleshoot. Send the
  whole problem statement and every output collected so far on each call.
- A config in `configs/`: Damira config audit. It runs locally.
- General protocol questions: answer them yourself.

If a Damira lookup comes back with no authoritative source, say so. Don't fill
the gap from memory.

## Devices
Advisor mode: never connect to network devices. Give the engineer the exact
commands and ask them to paste the output back.

## Where things go
- `configs/`: device configs to audit. Git-ignored; strip secrets anyway.
- `documents/`: MOPs, change controls, runbooks, incident reports. Only write
  what Damira data backs up.
- `notes/`: research notes and incident timelines.

## Document standards
- MOP: purpose, scope, prerequisites, numbered steps with expected output,
  verification, rollback, sign-off.
- Change control: RFC fields, risk, implementation summary, backout plan, CAB
  checklist.
- Runbook: trigger, diagnostic decision tree, resolution per cause, escalation.
- Incident report: timeline, impact, root cause, corrective actions.

## Environment
{environment}
{end}
"""

_INIT_README = """# Network operations workspace

Set up by `damira init`.

- `configs/`: device configs to audit (git-ignored)
- `documents/`: MOPs, change controls, runbooks, incident reports
- `notes/`: research notes and incident timelines

Try:
- "Audit the config in configs/core-rtr-01.cfg"
- "Plan the IOS-XE upgrade from 17.6.5 to 17.12.4 for our core switches"
- "Known bugs and CVEs in PAN-OS 11.1?"
- "BGP to the ISP keeps flapping. Here's the show output: ..."
"""


def _init_environment(a) -> str:
    rows = [
        ("Vendors", ", ".join(a.vendor)),
        ("Environment", a.environment),
        ("Change management", a.change_mgmt),
        ("Ticketing", a.ticketing),
        ("Naming convention", a.naming),
    ]
    lines = [f"- {k}: {v}" for k, v in rows if v]
    if a.platform:
        lines.append("- Platforms:")
        lines.extend(f"  - {p}" for p in a.platform)
    return "\n".join(lines) or "- Not set yet. Re-run `damira init` with your vendors and platforms."


def _init_ecosystem(a) -> str:
    """Ecosystem section (#480); lives in ecosystem.py so this file stays small."""
    entries = getattr(a, "ecosystem", None) or []
    change_type = getattr(a, "change_type", "") or ""
    if not entries and not change_type:
        return ""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ecosystem  # noqa: E402 — imported lazily, only when init is given ecosystem answers

    try:
        return "\n\n" + ecosystem.render_block(entries, change_type)
    except ValueError as exc:
        raise DamiraError(str(exc)) from exc


def _init_capabilities(a, root: Path) -> str:
    """Automation capabilities (#474): orchestration MCP servers found in this workspace's
    configs. Server names only; `--no-detect` skips it."""
    if getattr(a, "no_detect", False):
        return ""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ecosystem  # noqa: E402

    try:
        block = ecosystem.render_capabilities(ecosystem.classify(ecosystem.load_workspace_servers(root)))
    except Exception:  # noqa: BLE001 — detection is best-effort; init must still work
        return ""
    return "\n\n" + block if block else ""


def _init_write_block(path: Path, block: str) -> str:
    """Insert or replace the managed block; never touch anything outside it."""
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return "created"
    text = path.read_text(encoding="utf-8")
    if INIT_BEGIN in text and INIT_END in text:
        start = text.index(INIT_BEGIN)
        end = text.index(INIT_END) + len(INIT_END)
        new = text[:start] + block.rstrip("\n") + text[end:]
        if new == text:
            return "unchanged"
        path.write_text(new, encoding="utf-8")
        return "updated"
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    path.write_text(text + sep + block, encoding="utf-8")
    return "appended to existing file"


def cmd_init(a) -> str:
    root = Path(a.dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    report = []

    for d in INIT_DIRS:
        target = root / d
        report.append(f"{d}/: {'exists' if target.is_dir() else 'created'}")
        target.mkdir(exist_ok=True)

    # Device configs carry secrets; keep them out of git by default.
    ignore = root / "configs" / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# Device configs carry secrets. Nothing here is committed.\n*\n!.gitignore\n",
                          encoding="utf-8")
        report.append("configs/.gitignore: created")

    block = _INIT_BODY.format(begin=INIT_BEGIN, end=INIT_END, environment=_init_environment(a) + _init_ecosystem(a) + _init_capabilities(a, root))
    for name in INIT_TARGETS[a.target]:
        report.append(f"{name}: {_init_write_block(root / name, block)}")

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(_INIT_README, encoding="utf-8")
        report.append("README.md: created")

    return f"Damira workspace ready in {root}\n" + "\n".join(f"  {r}" for r in report)


def cmd_validate(a) -> "None":
    """Local, deterministic checks on generated automation (#471). Never calls the API.

    Exits here rather than returning text: validate prints its own report, and a failed
    check must surface as a non-zero exit so the agent treats it as unfinished work.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validate  # noqa: E402 — imported lazily, only for this subcommand

    sys.exit(validate.main_with_args(a))


def cmd_stats(a) -> "None":
    """First-pass rate, retries-to-green, top failing rules and model cost from the local
    workflow log (#475). Never calls the API."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import stats  # noqa: E402 — imported lazily, only for this subcommand

    sys.exit(stats.main_with_args(a))


def cmd_workbook(a) -> "None":
    """Render a workbook spec to .xlsx + index.html (#484). Needs no pip install: the
    renderer finds openpyxl locally or runs itself under `uv run --with openpyxl`."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import render_workbook  # noqa: E402 — imported lazily, only for this subcommand

    sys.exit(render_workbook.main(a.args))


def cmd_diagram(a) -> "None":
    """Topology diagrams (#485): `diagram build` parses configs into topology.json, `diagram
    render` draws it. Stdlib only; the optional pptx comes via `uv run --with python-pptx`."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    args = list(a.args)
    action = args.pop(0) if args else ""
    if action == "build":
        import topology  # noqa: E402 — imported lazily, only for this subcommand
        sys.exit(topology.main(args))
    if action == "render":
        import render_diagram  # noqa: E402 — imported lazily, only for this subcommand
        sys.exit(render_diagram.main(args))
    print("usage: damira diagram build <configs-dir> -o documents/<id>/topology.json\n"
          "       damira diagram render documents/<id>/topology.json [--pptx] [--redact --out-dir DIR]",
          file=sys.stderr)
    sys.exit(2)


def cmd_docx(a) -> "None":
    """Convert a MOP / change control / incident report to .docx + .html (#485). Needs no
    pip install: the converter finds python-docx locally or runs under `uv run --with`."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import md_to_docx  # noqa: E402 — imported lazily, only for this subcommand

    sys.exit(md_to_docx.main(a.args))


def cmd_render(a) -> "None":
    """Golden config templates (#473), rendered locally in a jinja2 sandbox. Never calls the API."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import golden  # noqa: E402 — imported lazily, only for this subcommand

    sys.exit(golden.main_with_args(a))


def cmd_lab(a) -> "None":
    """Test a change in a ContainerLab lab before production (#477): preflight, validate,
    or run (deploy, apply, checks, report, destroy). Runs locally; never calls the API."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lab_run  # noqa: E402 — imported lazily, only for this subcommand

    sys.exit(lab_run.main(a.args))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="damira",
        description="Damira network-engineering domain tools. Non-zero exit means the "
                    "result is NOT an answer — do not use stdout as source material.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search-vendor-docs", help="Authoritative vendor documentation")
    s.add_argument("query")
    s.add_argument("--vendor", default="", help="cisco, juniper, arista, palo_alto, fortinet")
    s.set_defaults(func=cmd_search_vendor_docs)

    s = sub.add_parser("search-cve", help="CVEs and security advisories from NVD")
    s.add_argument("query", help='CVE ID or description')
    s.add_argument("--product", default="")
    s.set_defaults(func=cmd_search_cve)

    s = sub.add_parser("search-release-notes", help="Version-specific bugs and caveats")
    s.add_argument("product")
    s.add_argument("--version", default="")
    s.set_defaults(func=cmd_search_release_notes)

    s = sub.add_parser("troubleshoot", help="structured diagnosis of an active fault")
    s.add_argument("problem")
    s.add_argument("--platform", default="")
    s.add_argument("--show-output", default="", help="show output, or '-' to read stdin")
    s.set_defaults(func=cmd_troubleshoot)

    s = sub.add_parser("upgrade-plan", help="Structured upgrade assessment")
    s.add_argument("product")
    s.add_argument("current_version")
    s.add_argument("target_version")
    s.add_argument("--environment", default="")
    s.set_defaults(func=cmd_upgrade_plan)

    s = sub.add_parser("agent", help="Full agent pipeline — slower, use when no tool fits")
    s.add_argument("message", help="the question, or '-' to read stdin")
    s.set_defaults(func=cmd_agent)

    s = sub.add_parser("whoami", help="Show which key and endpoint are in use")
    s.set_defaults(func=cmd_whoami)

    s = sub.add_parser("install-mcp", help="Register the bundled MCP server with Cursor / Claude Desktop")
    s.add_argument("--target", default="cursor", choices=["cursor", "claude-desktop", "all"])
    s.add_argument("--force", action="store_true", help="Overwrite an existing 'damira' entry")
    s.set_defaults(func=cmd_install_mcp)

    s = sub.add_parser("init", help="Set up a folder as a Damira network-operations workspace")
    s.add_argument("--dir", default=".", help="workspace folder (default: current)")
    s.add_argument("--target", default="both", choices=sorted(INIT_TARGETS),
                   help="which agent's instructions file to write (CLAUDE.md, AGENTS.md, or both)")
    s.add_argument("--vendor", action="append", default=[], help="repeatable, e.g. --vendor Cisco")
    s.add_argument("--platform", action="append", default=[],
                   help='repeatable, e.g. --platform "Core switches: Catalyst 9300, IOS-XE 17.9.4"')
    s.add_argument("--environment", default="", help="production, lab, or both")
    s.add_argument("--change-mgmt", default="", help="e.g. ITIL with weekly CAB")
    s.add_argument("--ticketing", default="", help="e.g. ServiceNow")
    s.add_argument("--naming", default="", help="e.g. SITE-ROLE-NN (CHI-RTR-01)")
    s.add_argument("--ecosystem", action="append", default=[], metavar="CATEGORY=CONNECTOR[:KEY]",
                   help='repeatable, e.g. --ecosystem "itsm=ServiceNow:NetOps" (categories: itsm, '
                        'tracker, chat, paging, observability, source-of-truth, docs, '
                        'automation, testing, iac)')
    # Same list as ecosystem.CHANGE_TYPES; render_block rejects anything else.
    s.add_argument("--change-type", default="", choices=["", "standard", "normal", "emergency"],
                   help="default change type for change requests")
    s.add_argument("--no-detect", action="store_true",
                   help="don't list the NetBox/AAP/pyATS/Terraform MCP servers found in this workspace")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("validate", help="Lint/syntax-check generated playbooks, Terraform, Python, "
                       "Jinja and configs locally (exit 1 on any failure)")
    # Mirrors validate.build_parser; declared here so a problem in validate.py can only
    # break `damira validate`, never the API commands.
    s.add_argument("path", help="file or directory to validate")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.add_argument("--host", default=os.environ.get("DAMIRA_HOST", "cli"),
                   choices=["cli", "claude-code", "cursor"], help=argparse.SUPPRESS)
    s.add_argument("--skill", default="", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("stats", help="First-pass rate, retries-to-green, failing rules and model cost "
                       "from the local workflow log")
    s.add_argument("--since", default="", help="7d, 24h, or YYYY-MM-DD")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("workbook", add_help=False,
                       help="Render documents/<id>/workbook.json to .xlsx + index.html, flagging "
                            "commands the saved evidence doesn't back (run `damira workbook -h`)")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_workbook)

    s = sub.add_parser("diagram", add_help=False,
                       help="Draw the topology: `diagram build configs/ -o topology.json`, then "
                            "`diagram render topology.json` (SVG, HTML, Mermaid, D2; --pptx optional)")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_diagram)

    s = sub.add_parser("docx", add_help=False,
                       help="Convert documents/<id>/mop.md (or change-control.md, incident-report.md) "
                            "to .docx + a .html preview (run `damira docx -h`)")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_docx)

    s = sub.add_parser("lab", add_help=False,
                       help="Test a change in a ContainerLab lab: `lab preflight`, `lab validate "
                            "topo.clab.yml`, `lab run topo.clab.yml --apply change.yml --checks "
                            "lab.checks.json` (always destroys the lab)")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_lab)

    s = sub.add_parser("render", help="Render a golden config template (NTP, AAA/TACACS+, SNMPv3, "
                       "syslog, banner) for IOS, NX-OS, EOS or Junos")
    s.add_argument("task", nargs="?", help="ntp, aaa_tacacs, snmpv3, syslog, banner")
    s.add_argument("--platform", help="cisco_ios, cisco_nxos, arista_eos, juniper_junos")
    s.add_argument("--vars", help="YAML/JSON vars file; values written env:NAME come from the environment")
    s.add_argument("-o", "--output", help="write here instead of stdout, e.g. configs/rtr1-ntp.cfg")
    s.add_argument("--force", action="store_true", help="overwrite --output if it exists")
    s.add_argument("--secrets", choices=["resolve", "mask", "ansible"],
                   help="env: values — resolve (default with -o), mask (default on stdout), "
                        "or ansible lookups")
    s.add_argument("--list", action="store_true", help="list available templates")
    s.set_defaults(func=cmd_render)

    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        print(args.func(args))
    except DamiraError as exc:
        die(str(exc), getattr(exc, "code", EXIT_ERROR))


if __name__ == "__main__":
    main()
