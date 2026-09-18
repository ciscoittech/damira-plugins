#!/usr/bin/env python3
"""Damira MCP server — stdio, standard library only.

Why this exists alongside scripts/damira.py: some people want MCP. Cursor, Claude Code,
Claude Desktop, and Windsurf all speak it, and Claude Desktop has no shell at all, so the
script path cannot reach it. This gives every one of them the same tools.

Why it is hand-rolled rather than FastMCP: FastMCP means `mcp[cli]` + `aiohttp`, which
means pip or uvx, which is exactly the install friction the no-MCP work removed. MCP over
stdio is newline-delimited JSON-RPC 2.0 — small enough to implement directly, and doing so
keeps the whole plugin dependency-free. Verified working against Cursor 2026.08.04.

The API logic is NOT duplicated. This imports scripts/damira.py and calls the same
functions the CLI uses, so message templating, auth resolution, and the refusal check
have exactly one implementation. A DamiraError becomes an MCP result with isError set —
the same "this is not an answer" contract the CLI expresses as a non-zero exit.

Install:  ~/.damira/bin/damira install-mcp
Manual:   add to ~/.cursor/mcp.json, then `agent mcp enable damira`
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import damira  # noqa: E402  — path must be set first

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "damira", "version": damira.VERSION}


def _s(desc: str, **props):
    required = [k for k, v in props.items() if v.pop("_required", False)]
    return {"type": "object", "properties": props, "required": required}


TOOLS = [
    {
        "name": "damira_search_vendor_docs",
        "description": (
            "Search official vendor documentation (cisco.com, juniper.net, arista.com, "
            "paloaltonetworks.com, fortinet.com) for authoritative, version-specific "
            "procedures. USE WHEN you need exact CLI syntax for a platform and version, or "
            "platform-specific behaviour beyond your training data. DO NOT use for general "
            "protocol knowledge — you already know how BGP and OSPF work."
        ),
        "inputSchema": _s(
            "",
            query={"type": "string", "description": "What to search for", "_required": True},
            vendor={"type": "string", "description": "cisco, juniper, arista, palo_alto, fortinet"},
        ),
    },
    {
        "name": "damira_search_cve",
        "description": (
            "Search CVEs and security advisories from NVD, CVE.org, and vendor advisories. "
            "USE WHEN the user asks about a specific CVE, whether a version is vulnerable, or "
            "for security posture before an upgrade. Returns real-time data you do not have."
        ),
        "inputSchema": _s(
            "",
            query={"type": "string", "description": "CVE ID or description", "_required": True},
            product={"type": "string", "description": 'e.g. "Cisco IOS XE", "PAN-OS"'},
        ),
    },
    {
        "name": "damira_search_release_notes",
        "description": (
            "Search release notes, upgrade guides, and known issues for a specific platform "
            "version. USE WHEN planning an upgrade and you need the bugs and caveats in the "
            "target release."
        ),
        "inputSchema": _s(
            "",
            product={"type": "string", "description": 'e.g. "Cisco IOS XE"', "_required": True},
            version={"type": "string", "description": 'e.g. "17.9.4"'},
        ),
    },
    {
        "name": "damira_troubleshoot",
        "description": (
            "CCIE-level structured diagnosis: gathers evidence, isolates the fault domain, ranks "
            "likely causes, and gives the exact CLI to confirm and fix. USE WHEN there is an active fault and the user has symptoms or show "
            "output. Each call is INDEPENDENT and remembers nothing — always send the "
            "cumulative problem statement and all output collected so far, not just the newest "
            "paste. Sending only the delta makes the second diagnosis worse than the first."
        ),
        "inputSchema": _s(
            "",
            problem={"type": "string", "description": "Cumulative problem description", "_required": True},
            platform={"type": "string", "description": 'e.g. "Cisco IOS-XE"'},
            show_output={"type": "string", "description": "All show output collected so far"},
        ),
    },
    {
        "name": "damira_upgrade_plan",
        "description": (
            "Structured upgrade assessment: path, prerequisites, risks, maintenance window, "
            "rollback. USE WHEN planning a named version-to-version upgrade. YOU write the MOP "
            "and change control from this data — also call damira_search_cve and "
            "damira_search_release_notes on the target version first."
        ),
        "inputSchema": _s(
            "",
            product={"type": "string", "_required": True},
            current_version={"type": "string", "_required": True},
            target_version={"type": "string", "_required": True},
            environment={"type": "string", "description": "Device count, role, prod/lab"},
        ),
    },
    {
        "name": "damira_agent",
        "description": (
            "Full agent pipeline for complex multi-domain queries. SLOWER (30-60s). Prefer the "
            "specialised tools above when the intent is clear; use this only when none fit."
        ),
        "inputSchema": _s("", message={"type": "string", "_required": True}),
    },
    {
        "name": "analyze_config",
        "description": (
            "Regex security audit of a network device configuration — weak credentials, type 7 "
            "passwords, SNMP communities, HTTP management, missing NTP/logging/banner. RUNS "
            "LOCALLY: the config text never leaves this machine, which is why it is safe to "
            "pass production configs."
        ),
        "inputSchema": _s(
            "",
            config_text={"type": "string", "_required": True},
            check_type={"type": "string", "enum": ["security", "best_practices", "all"]},
        ),
    },
]


class _Args:
    """damira.py's cmd_* functions take an argparse Namespace; this stands in for one."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def dispatch(name: str, a: dict) -> str:
    if name == "damira_search_vendor_docs":
        return damira.cmd_search_vendor_docs(_Args(query=a["query"], vendor=a.get("vendor", "")))
    if name == "damira_search_cve":
        return damira.cmd_search_cve(_Args(query=a["query"], product=a.get("product", "")))
    if name == "damira_search_release_notes":
        return damira.cmd_search_release_notes(
            _Args(product=a["product"], version=a.get("version", ""))
        )
    if name == "damira_troubleshoot":
        return damira.cmd_troubleshoot(
            _Args(problem=a["problem"], platform=a.get("platform", ""),
                  show_output=a.get("show_output", ""))
        )
    if name == "damira_upgrade_plan":
        return damira.cmd_upgrade_plan(
            _Args(product=a["product"], current_version=a["current_version"],
                  target_version=a["target_version"], environment=a.get("environment", ""))
        )
    if name == "damira_agent":
        return damira.cmd_agent(_Args(message=a["message"]))
    if name == "analyze_config":
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import audit_config

        findings = audit_config.audit(a["config_text"], a.get("check_type", "all"))
        if not findings:
            return "No issues found in configuration analysis."
        lines = [f"Config Analysis Results ({len(findings)} issues found):", ""]
        for severity, message, line_no in findings:
            where = f"Line {line_no}: " if line_no else ""
            lines.append(f"[{severity}] {where}{message}")
            lines.append("")
        return "\n".join(lines)
    raise damira.DamiraError(f"unknown tool: {name}")


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(req: dict) -> None:
    method = req.get("method")
    rid = req.get("id")

    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }})
        return

    if method in ("notifications/initialized", "initialized"):
        return  # notification — no response

    if method == "ping":
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
        return

    if method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        return

    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            text = dispatch(name, args)
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }})
        except damira.DamiraError as exc:
            # isError is the MCP equivalent of the CLI's non-zero exit. Without it a
            # refusal reads as a normal answer, which is how a fabricated MOP happens.
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"Damira error: {exc}"}],
                "isError": True,
            }})
        except KeyError as exc:
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"Missing required argument: {exc}"}],
                "isError": True,
            }})
        except Exception as exc:  # noqa: BLE001 — never kill the server on one bad call
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"Damira tool failed: {type(exc).__name__}: {exc}"}],
                "isError": True,
            }})
        return

    if rid is not None:
        send({"jsonrpc": "2.0", "id": rid,
              "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(req)
        except Exception as exc:  # noqa: BLE001 — a malformed request must not end the session
            if req.get("id") is not None:
                send({"jsonrpc": "2.0", "id": req["id"],
                      "error": {"code": -32603, "message": str(exc)}})


if __name__ == "__main__":
    main()
