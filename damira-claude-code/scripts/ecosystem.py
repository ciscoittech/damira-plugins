#!/usr/bin/env python3
"""Ecosystem connectors (#480): which tools the engineer already uses, and what to hand them.

Damira drafts vendor-neutral records (a change request, an incident update, a task). The
engineer's own MCP connector (ServiceNow, Jira/JSM, monday, Freshservice, Slack...) does the
write, after they confirm. Damira ships no connector and holds no credentials for them.

Skills refer to categories as `~~itsm`, `~~tracker` and so on, never to concrete tool names:
the same connector shows up as `mcp__atlassian__*`, `mcp__plugin_<p>_<s>__*` or a UUID
depending on how it was installed.

Byte-identical in plugins/damira and plugins/damira-cursor. Stdlib only.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

# Category -> fingerprints matched against a server's name, URL host and package name.
CATEGORIES = {
    "itsm": ("servicenow", "service-now", "atlassian", "jira-service", "jsm", "freshservice",
             "zendesk", "bmc", "bmc-helix", "ivanti", "topdesk", "halo"),
    "tracker": ("atlassian", "jira", "linear", "monday", "asana", "clickup", "github", "gitlab",
                "azure-devops", "shortcut", "trello"),
    "chat": ("slack", "msteams", "ms-teams", "microsoft-teams", "webex", "discord", "mattermost",
             "zoom-chat", "zoom-team-chat", "google-chat"),
    "paging": ("pagerduty", "opsgenie", "victorops", "splunk-oncall", "incident-io", "incidentio",
               "firehydrant", "rootly", "xmatters"),
    "observability": ("datadog", "splunk", "grafana", "prometheus", "elastic", "newrelic",
                      "new-relic", "dynatrace", "sentry", "thousandeyes", "logicmonitor",
                      "solarwinds", "kentik", "zabbix", "librenms", "honeycomb"),
    "source-of-truth": ("netbox", "nautobot", "infoblox", "device42", "ipfabric", "ip-fabric",
                        "forward-networks", "suzieq"),
    # Orchestration targets (#474): Damira hands validated changes to these, never hosts them.
    "automation": ("ansible", "aap", "awx"),
    "testing": ("pyats", "genie"),
    "iac": ("terraform", "opentofu"),
    "docs": ("notion", "confluence", "sharepoint", "google-drive", "gdrive", "onedrive",
             "gitbook", "box"),
}

# What the optional third part of `--ecosystem CATEGORY=CONNECTOR[:X]` means per category.
SCOPE_LABEL = {
    "itsm": "assignment group or project",
    "tracker": "project",
    "chat": "channel",
    "paging": "service",
    "observability": "scope",
    "source-of-truth": "site or tenant",
    "automation": "organization or inventory",
    "testing": "testbed",
    "iac": "workspace",
    "docs": "space",
}

CHANGE_TYPES = ("standard", "normal", "emergency")

SCHEMAS = {
    "change_request": {
        "required": ("title", "description", "change_type", "cmdb_ci", "risk", "impact",
                     "assignment_group", "planned_start", "planned_end", "implementation_plan",
                     "backout_plan", "test_plan", "validate_report"),
        "optional": ("justification", "category", "affected_devices", "related_ref"),
    },
    "incident_update": {
        "required": ("incident_ref", "status", "summary", "impact", "cmdb_ci", "work_note",
                     "next_update"),
        "optional": ("urgency", "assignment_group", "category", "subcategory", "resolution"),
    },
    "task_item": {
        "required": ("title", "description", "assignee", "due", "parent_ref"),
        "optional": ("priority", "labels"),
    },
}

# ServiceNow field rules, same as the agent's ticketing tool
# (services/oncall-agent/src/tools/ticketing.py, #204).
SERVICENOW_RULES = {
    "categories": ("network", "hardware", "software", "security", "telecom", "request"),
    "subcategories": ("routing", "switching", "firewall", "wireless", "voice", "vpn", "dns",
                      "ntp", "certificate"),
    "default_category": "network",
    # priority 1-5 -> impact and urgency ("1" high .. "3" low)
    "impact_urgency": {1: "1", 2: "2", 3: "2", 4: "3", 5: "3"},
}


def servicenow_defaults(priority: int, assignment_group: str = "") -> dict:
    """assignment_group / impact / urgency the way the agent's ServiceNow tool fills them."""
    level = SERVICENOW_RULES["impact_urgency"].get(priority, "3")
    group = assignment_group or ("Network Operations Center" if priority <= 2
                                 else "Network Engineering")
    return {"assignment_group": group, "impact": level, "urgency": level,
            "category": SERVICENOW_RULES["default_category"]}


# Schema field -> the vendor's field. Jira/JSM and monday custom fields and columns are named
# per site, so these are the usual display names; confirm against the connector before writing.
MAPPINGS = {
    "change_request": {
        "ServiceNow": {
            "title": "short_description", "description": "description", "change_type": "type",
            "cmdb_ci": "cmdb_ci", "risk": "risk", "impact": "impact",
            "assignment_group": "assignment_group", "planned_start": "start_date",
            "planned_end": "end_date", "implementation_plan": "implementation_plan",
            "backout_plan": "backout_plan", "test_plan": "test_plan",
            "validate_report": "work_notes", "justification": "justification",
            "category": "category", "affected_devices": "task_ci (affected CIs)",
            "related_ref": "parent",
        },
        "Jira/JSM": {
            "title": "summary", "description": "description", "change_type": "Change type",
            "cmdb_ci": "Affected services / Assets object", "risk": "Change risk",
            "impact": "Impact", "assignment_group": "Team", "planned_start": "Planned start",
            "planned_end": "Planned end", "implementation_plan": "Implementation plan",
            "backout_plan": "Backout plan", "test_plan": "Test plan",
            "validate_report": "internal comment", "justification": "Change reason",
            "category": "Request type", "affected_devices": "Assets objects",
            "related_ref": "linked issue",
        },
        "monday": {
            "title": "item name", "description": "Description (long text)",
            "change_type": "Change type (status)", "cmdb_ci": "CI / device (text or connect)",
            "risk": "Risk (status)", "impact": "Impact (status)", "assignment_group": "Team (people)",
            "planned_start": "Timeline (start)", "planned_end": "Timeline (end)",
            "implementation_plan": "Implementation plan (long text)",
            "backout_plan": "Backout plan (long text)", "test_plan": "Test plan (long text)",
            "validate_report": "update", "justification": "Justification (long text)",
            "category": "Category (status)", "affected_devices": "Devices (connect boards)",
            "related_ref": "Linked item (connect boards)",
        },
        "Freshservice": {
            "title": "subject", "description": "description", "change_type": "change_type",
            "cmdb_ci": "assets", "risk": "risk", "impact": "impact", "assignment_group": "group_id",
            "planned_start": "planned_start_date", "planned_end": "planned_end_date",
            "implementation_plan": "planning_fields.rollout_plan",
            "backout_plan": "planning_fields.backout_plan",
            "test_plan": "custom_fields.test_plan", "validate_report": "private note",
            "justification": "planning_fields.reason_for_change", "category": "category",
            "affected_devices": "assets", "related_ref": "associated ticket",
        },
    },
    "incident_update": {
        "ServiceNow": {
            "incident_ref": "number", "status": "state", "summary": "short_description",
            "impact": "impact", "cmdb_ci": "cmdb_ci", "work_note": "work_notes",
            "next_update": "work_notes (next update at)", "urgency": "urgency",
            "assignment_group": "assignment_group", "category": "category",
            "subcategory": "subcategory", "resolution": "close_notes",
        },
        "Jira/JSM": {
            "incident_ref": "issue key", "status": "status (transition)", "summary": "summary",
            "impact": "Impact", "cmdb_ci": "Affected services / Assets object",
            "work_note": "internal comment", "next_update": "internal comment (next update at)",
            "urgency": "Urgency", "assignment_group": "Team", "category": "Request type",
            "subcategory": "Components", "resolution": "Resolution",
        },
        "monday": {
            "incident_ref": "item ID", "status": "Status (status)", "summary": "item name",
            "impact": "Impact (status)", "cmdb_ci": "CI / device (text or connect)",
            "work_note": "update", "next_update": "Next update (date)",
            "urgency": "Urgency (status)", "assignment_group": "Team (people)",
            "category": "Category (status)", "subcategory": "Subcategory (dropdown)",
            "resolution": "Resolution (long text)",
        },
        "Freshservice": {
            "incident_ref": "ticket id", "status": "status", "summary": "subject",
            "impact": "impact", "cmdb_ci": "assets", "work_note": "private note",
            "next_update": "private note (next update at)", "urgency": "urgency",
            "assignment_group": "group_id", "category": "category",
            "subcategory": "sub_category", "resolution": "resolution notes",
        },
    },
    "task_item": {
        "ServiceNow": {
            "title": "short_description", "description": "description", "assignee": "assigned_to",
            "due": "due_date", "parent_ref": "parent", "priority": "priority",
            "labels": "sys_tags (label entries)",
        },
        "Jira/JSM": {
            "title": "summary", "description": "description", "assignee": "assignee",
            "due": "duedate", "parent_ref": "parent", "priority": "priority", "labels": "labels",
        },
        "monday": {
            "title": "subitem name", "description": "update", "assignee": "Owner (people)",
            "due": "Due date (date)", "parent_ref": "parent item", "priority": "Priority (status)",
            "labels": "Tags",
        },
        "Freshservice": {
            "title": "title", "description": "description", "assignee": "agent_id",
            "due": "due_date", "parent_ref": "parent ticket/change", "priority": "priority",
            "labels": "tags",
        },
    },
}


# --- detection --------------------------------------------------------------------------

_PACKAGE = re.compile(r"^@?[\w.-]+(/[\w.-]+)?(@[\w.-]+)?$")


def _servers_from(block, source: str) -> "list[dict]":
    """name + URL host + package name for each server. Never env, headers, query or path."""
    out = []
    if not isinstance(block, dict):
        return out
    for name, spec in block.items():
        if not isinstance(spec, dict):
            spec = {}
        host = ""
        url = spec.get("url") or spec.get("serverUrl") or ""
        if isinstance(url, str) and url:
            try:
                host = urlparse(url).hostname or ""
            except ValueError:
                host = ""
        package = ""
        args = spec.get("args")
        if isinstance(args, list):
            for arg in args:
                if not isinstance(arg, str):
                    continue
                # Wrappers like `npx mcp-remote https://mcp.atlassian.com/v1/sse` carry the
                # vendor only in the URL argument.
                if not host and arg.startswith(("http://", "https://")):
                    try:
                        host = urlparse(arg).hostname or ""
                    except ValueError:
                        pass
                elif (not package and _PACKAGE.match(arg)
                        and ("mcp" in arg.lower() or "server" in arg.lower())):
                    package = arg
        out.append({"name": str(name), "host": host, "package": package, "source": source})
    return out


def load_mcp_servers(paths, project: "str | None" = None) -> "list[dict]":
    """Read MCP configs (`mcpServers`; plus `projects[project].mcpServers` for ~/.claude.json).

    Missing or malformed files are skipped. Best-effort: never raises for bad input.
    """
    servers = []
    for p in paths:
        path = Path(p)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        servers += _servers_from(data.get("mcpServers"), str(path))
        if project and isinstance(data.get("projects"), dict):
            proj = data["projects"].get(project)
            if isinstance(proj, dict):
                servers += _servers_from(proj.get("mcpServers"), str(path))
    return servers


def load_workspace_servers(root, home=None) -> "list[dict]":
    """Servers both hosts would load for this workspace: Claude Code's .mcp.json and
    ~/.claude.json project entry, Cursor's .cursor/mcp.json and ~/.cursor/mcp.json."""
    root = Path(root)
    home = Path(home) if home else Path.home()
    servers = load_mcp_servers([root / ".mcp.json", root / ".cursor" / "mcp.json",
                                home / ".cursor" / "mcp.json"])
    return servers + load_mcp_servers([home / ".claude.json"], project=str(root))


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower())


def classify(servers) -> "dict[str, list[str]]":
    """{category: [server names]} for recognised servers; unknown servers are left out."""
    found: "dict[str, list[str]]" = {}
    for s in servers:
        hay = "-" + _normalize(" ".join((s.get("name", ""), s.get("host", ""),
                                         s.get("package", "")))) + "-"
        # Match at a word start, so "team-slack" and "mcp.atlassian.com" hit but
        # "unboxed" does not.
        hits = {c: [fp for fp in prints if f"-{fp}" in hay] for c, prints in CATEGORIES.items()}
        matched = {fp for fps in hits.values() for fp in fps}
        for category, fps in hits.items():
            # A fingerprint inside a longer match elsewhere is not a hit of its own:
            # "splunk-oncall" is paging, not also observability via "splunk".
            if any(not any(fp != longer and fp in longer for longer in matched) for fp in fps):
                names = found.setdefault(category, [])
                if s["name"] not in names:
                    names.append(s["name"])
    return found


def safe_name(name: str) -> str:
    """Server names go into model context; keep them short and plain."""
    return re.sub(r"[^\w.@/-]", "_", name)[:64]


def describe(found: "dict[str, list[str]]") -> str:
    """One line for session-start context: categories and server names only."""
    parts = [f"~~{c}: {', '.join(safe_name(n) for n in names)}"
             for c in CATEGORIES for names in [found.get(c)] if names]
    return "; ".join(parts)


# --- init -------------------------------------------------------------------------------

def _one_line(text: str) -> str:
    """User input goes into CLAUDE.md/AGENTS.md; it must not start new markdown lines."""
    return " ".join(str(text).split())


def parse_entry(raw: str) -> "tuple[str, str, str]":
    """`itsm=ServiceNow:NetOps` -> ("itsm", "ServiceNow", "NetOps")."""
    raw = _one_line(raw)
    if "=" not in raw:
        raise ValueError(f"--ecosystem expects CATEGORY=CONNECTOR[:KEY_OR_GROUP], got {raw!r}")
    category, rest = raw.split("=", 1)
    category = category.strip().lower().lstrip("~")
    if category not in CATEGORIES:
        raise ValueError(f"unknown ecosystem category {category!r}; "
                         f"use one of: {', '.join(CATEGORIES)}")
    connector, _, scope = rest.partition(":")
    if not connector.strip():
        raise ValueError(f"--ecosystem {raw!r} names no connector")
    return category, connector.strip(), scope.strip()


def render_block(entries, change_type: str = "") -> str:
    """The Ecosystem section `damira init` writes inside its managed block."""
    lines = [
        "## Ecosystem",
        "The engineer's own connectors. Refer to them by category (`~~itsm`, `~~chat`...);",
        "tool names vary by install, so find them with tool search. Damira drafts the",
        "record (see the plugin's CONNECTORS.md); write it only after the engineer confirms.",
    ]
    for raw in entries:
        category, connector, scope = parse_entry(raw) if isinstance(raw, str) else raw
        connector, scope = _one_line(connector), _one_line(scope)
        extra = f" ({SCOPE_LABEL[category]}: {scope})" if scope else ""
        lines.append(f"- ~~{category}: {connector}{extra}")
    if change_type:
        if change_type not in CHANGE_TYPES:
            raise ValueError(f"--change-type must be one of: {', '.join(CHANGE_TYPES)}")
        lines.append(f"- Default change type: {change_type}")
    return "\n".join(lines)


# --- orchestration (#474) ---------------------------------------------------------------

ORCHESTRATION = ("source-of-truth", "automation", "testing", "iac")

HANDOFFS = {
    "source-of-truth": "intended state (devices, interfaces, VLANs, prefixes) as the input "
                       "to a change",
    "automation": "launch the validated playbook as a job in check mode (job_type=check) for "
                  "a diff; a run-mode launch needs the engineer's approval",
    "testing": "pyATS/Genie pre/post snapshots and diffs, each device call approved by the "
               "engineer; config push is blocked in advisor mode",
    "iac": "provider and module docs lookups; plan locally, apply only from the engineer's "
           "own pipeline (run/apply tools are blocked in advisor mode)",
}


def render_capabilities(found: "dict[str, list[str]]") -> str:
    """The Automation capabilities section `damira init` writes; "" when nothing is found."""
    cats = [c for c in ORCHESTRATION if found.get(c)]
    if not cats:
        return ""
    lines = [
        "## Automation capabilities",
        "Detected in this workspace's MCP config (server names only). The",
        "source-of-truth-change skill hands validated changes to them; refer to them by",
        "placeholder and find their tools with tool search.",
    ]
    for c in cats:
        names = ", ".join(_one_line(safe_name(n)) for n in found[c])
        lines.append(f"- ~~{c}: {names}: {HANDOFFS[c]}")
    return "\n".join(lines)


# The gate (hooks-handlers/device_gate.py in both plugins) matches the server, then the
# verb in the tool name. Tool names vary by server version, so unknown verbs on a matched
# server ask rather than pass: fail toward the human.
_GATED = ("iac", "testing", "automation")
_READ = {"list", "get", "search", "describe", "read", "fetch", "find", "lookup", "retrieve",
         "query", "status", "resolve", "docs", "help"}
_LAUNCH = {"launch", "run", "relaunch", "execute", "exec", "start", "trigger"}
_PUSH = {"configure", "apply", "push", "commit", "rollback", "reload", "deploy", "write",
         "erase", "clear", "delete", "destroy"}
_IAC_WRITE = _PUSH | _LAUNCH | {"create", "update", "action", "import", "cancel", "discard",
                                "override", "lock", "unlock", "taint", "upload", "set", "queue"}

_DENY = {
    "testing": "Blocked: Damira is in advisor mode and does not push configuration through "
               "pyATS. Hand the engineer the validated change and the command to apply it.",
    "iac": "Blocked: Damira is in advisor mode and does not run or apply Terraform. Plan "
           "locally and hand the engineer the plan; they apply it from their own pipeline.",
}
_ASK = {
    "automation": "This launches an automation job that is not in check mode, so it can change "
                  "devices. Damira hands off in check mode (job_type=check); approve only if "
                  "you intend a live run.",
    "automation-check": "This launches an automation job in check mode (job_type=check). AAP "
                        "honours that only if the job template prompts for job type on launch "
                        "(ask_job_type_on_launch); otherwise it runs the template's own type, "
                        "which may be a live run. Approve once you have confirmed the prompt.",
    "testing": "This pyATS call connects to a device. Damira is in advisor mode, so it's your "
               "call: approve it if the device and command are what you expect.",
    "iac": "Damira is in advisor mode and does not recognise this Terraform tool as a lookup. "
           "Approve it only if it changes nothing.",
}


def _tokens(text: str) -> "list[str]":
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _check_mode(tool_input, verbs: "set[str]") -> bool:
    """True only for a job-template launch whose own job_type (top level) is check.

    extra_vars/extra_data are playbook variables, so a job_type inside them changes
    nothing; workflow job templates have no job type at all.
    """
    if "workflow" in verbs or not isinstance(tool_input, dict):
        return False
    return str(tool_input.get("job_type", "")).strip().lower() == "check"


def gate_category(server: str, hint: str = "") -> "str | None":
    """automation / testing / iac for an orchestration server, else None."""
    if "damira" in server.lower():
        return None
    found = classify([{"name": server, "host": hint, "package": ""}])
    return next((c for c in _GATED if c in found), None)


def gate_mcp(tool_name: str, tool_input=None, hint: str = "", mode: str = "advisor",
             strict: bool = False) -> "tuple[str, str] | None":
    """("allow" | "ask" | "deny", reason) for an orchestration MCP call; None if unrelated.

    `tool_name` is `mcp__<server>__<tool>` (Claude Code) or a bare tool name with the
    server's URL host or command in `hint` (Cursor).
    """
    parts = tool_name.split("__")
    if len(parts) >= 3 and parts[0] == "mcp":
        server, tool = "__".join(parts[1:-1]), parts[-1]
    else:
        server, tool = "", tool_name
    category = gate_category(server, hint)
    if not category:
        return None
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            tool_input = {}
    noise = set(CATEGORIES[category]) | {"mcp", "server", "tool"}
    tokens = [t for t in _tokens(tool) if t not in noise]
    verbs, first = set(tokens), (tokens[0] if tokens else "")

    decision = "ask"
    if category == "automation":
        if first in _READ:
            decision = "allow"
        elif verbs & _LAUNCH and _check_mode(tool_input, verbs):
            # Still asks: the gate can't see whether the template prompts for job type.
            return "ask", _ASK["automation-check"]
    elif category == "testing":
        if verbs & _PUSH:
            decision = "deny"
        elif first in _READ:
            decision = "allow"
    elif first in _READ:  # iac
        decision = "allow"
    elif verbs & _IAC_WRITE:
        decision = "deny"

    elevated = mode in ("guided", "lab")
    if decision == "deny" and elevated:
        decision = "ask"  # never auto-run a change, whatever the mode
    elif decision == "ask" and strict and not elevated:
        decision = "deny"
    if decision == "allow":
        return "allow", ""
    if decision == "deny":
        return "deny", _DENY.get(category, "Blocked: Damira is in advisor mode. " + _ASK[category])
    return "ask", _ASK[category]
