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
  1. DAMIRA_API_KEY environment variable
  2. ~/.damira/config  (INI-ish `key = value`, or a bare key on the first line)
  3. the shared demo key — 50 queries/day, so people can try it before signing up

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
TIMEOUT = 300
VERSION = "0.2.2"

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


def resolve_key() -> "tuple[str, bool]":
    """Return (api_key, is_demo)."""
    key = os.environ.get("DAMIRA_API_KEY", "").strip()
    if key:
        return key, False

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
                            return value, False
                else:
                    return line, False
        except OSError:
            pass  # fall through to the demo key rather than hard-failing on a config read

    return DEMO_KEY, True


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
                "and export DAMIRA_API_KEY, or write it to ~/.damira/config")
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
    key, is_demo = resolve_key()
    masked = f"{key[:8]}…{key[-4:]}" if len(key) > 14 else key
    source = "demo key (50 queries/day)" if is_demo else (
        "DAMIRA_API_KEY" if os.environ.get("DAMIRA_API_KEY", "").strip() else str(CONFIG_PATH)
    )
    url = os.environ.get("DAMIRA_API_URL", DEFAULT_API_URL)
    mode = os.environ.get("DAMIRA_EXECUTION_MODE", "advisor")
    lines = [f"key:      {masked}", f"source:   {source}", f"endpoint: {url}", f"mode:     {mode}"]
    if is_demo:
        lines.append("")
        lines.append("Using the shared demo key. For your own: https://damiraai.com/dashboard/api-keys")
        lines.append("Then: export DAMIRA_API_KEY=... (or write it to ~/.damira/config)")
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

    s = sub.add_parser("troubleshoot", help="GIDRP diagnosis of an active fault")
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

    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        print(args.func(args))
    except DamiraError as exc:
        die(str(exc), getattr(exc, "code", EXIT_ERROR))


if __name__ == "__main__":
    main()
