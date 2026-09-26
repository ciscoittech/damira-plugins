#!/usr/bin/env python3
"""Local network-config security audit — regex, not AI, and deliberately local.

Ported from analyze_config() in services/oncall-mcp/damira_mcp/server.py. It stays on
the engineer's machine on purpose: config text is exactly the material that must not
leave the network, and shipping it to an API to run a few regexes would contradict the
PII-and-local-processing posture the product is sold on.

Every finding carries a stable rule ID (IOS-010, JUN-001, ...). `damira validate`
records those IDs, never the config text, in the local workflow log (#475).

Coverage is a baseline, not exhaustive: IOS/IOS-XE in depth, plus a handful of rules
each for Junos, EOS and NX-OS. The vendor is detected from the text; --vendor overrides.

Standard library only — see scripts/damira.py for why.

Exit codes: 0 = audit ran (findings or not), 1 = could not read input.
Findings are not an error; a clean config and a dirty one both exit 0.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
VENDORS = ("ios", "nxos", "eos", "junos")
# Detected but not audited: running IOS rules on these produces noise, not findings.
UNSUPPORTED = "unknown"

# (rule_id, pattern, message, severity) — matched per line, IOS-family syntax.
LINE_RULES = [
    # EOS stores `enable password sha512 $6$...` hashed; that is not the IOS plaintext form.
    ("IOS-001", r"^\s*enable password(?!\s+(?:sha512|5|8|9)\s)", "Use 'enable secret' instead of 'enable password'", "HIGH"),
    ("IOS-002", r"password 7 ", "Type 7 passwords are trivially reversible", "HIGH"),
    ("IOS-005", r"^\s*ip http server", "HTTP management is insecure — use HTTPS", "MEDIUM"),
    ("IOS-006", r"^\s*no service password-encryption", "Enable password encryption", "HIGH"),
    # `password 5|8|9 <hash>` (NX-OS, IOS type 8/9) is hashed; `password 7` is IOS-002's job.
    ("IOS-007", r"^\s*username \S+ .*\bpassword\b(?!\s+[5789]\s)", "Consider 'secret' instead of 'password'", "MEDIUM"),
]

SNMP_COMMUNITY_RE = re.compile(r"^\s*snmp-server community\s+\S+(.*)$", re.IGNORECASE)
# Bare "password cisco" / "password 0 cisco" — the plaintext line password used under
# line con/vty/aux. "password 7 ..." is IOS-002's job.
PLAINTEXT_LINE_PASSWORD_RE = re.compile(r"^password\s+(?:0\s+)?\S+$", re.IGNORECASE)
TRANSPORT_TELNET_RE = re.compile(r"^transport\s+input\b.*\b(telnet|all)\b", re.IGNORECASE)


def _f(rule_id: str, severity: str, message: str, line_no: int = 0) -> dict:
    return {"rule_id": rule_id, "severity": severity, "message": message, "line": line_no}


# `damira render` stamps its platform on line 1; a fragment carries no other vendor signal.
_GOLDEN_PLATFORMS = {"cisco_ios": "ios", "cisco_nxos": "nxos", "arista_eos": "eos", "juniper_junos": "junos"}
_GOLDEN_STAMP = re.compile(r"[!#] Damira golden template: \w+ \((\w+)\)")
# Lines no golden fragment renders: their presence means a full config wearing a stamp.
_FULL_CONFIG = re.compile(r"^(hostname|interface|router|version|line|end|vlan|system|interfaces)\b", re.MULTILINE)


def golden_fragment_vendor(config_text: str) -> "str | None":
    """Audit vendor of a `damira render` fragment, or None if the text is not one.

    The stamp counts only on line 1, and only when the body is fragment-shaped for that
    vendor and no content signal names another vendor. Anything else is audited as a
    full config, so one comment line cannot hide whole-config findings.
    """
    first, _, body = config_text.lstrip("\ufeff").partition("\n")
    m = _GOLDEN_STAMP.match(first)
    vendor = _GOLDEN_PLATFORMS.get(m.group(1)) if m else None
    if not vendor:
        return None
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and ln.strip()[0] not in "!#"]
    set_style = [ln.startswith(("set ", "delete ")) for ln in lines]
    if vendor == "junos" and not all(set_style):
        return None
    if vendor != "junos" and (any(set_style) or _FULL_CONFIG.search(body)):
        return None
    by_content = _detect_by_content(config_text)
    if by_content not in ("ios", vendor):  # "ios" is also the no-signal default
        return None
    return vendor


def detect_vendor(config_text: str) -> str:
    """Best-effort vendor guess. IOS is the default for anything Cisco-shaped.

    Returns UNSUPPORTED ("unknown") for FortiOS, PAN-OS and IOS-XR, which have no rules
    here yet — auditing them as IOS flagged every correct config.
    """
    return golden_fragment_vendor(config_text) or _detect_by_content(config_text)


def _detect_by_content(text: str) -> str:
    if (re.search(r"^!! IOS XR", text, re.MULTILINE)
            or re.search(r"^set (deviceconfig|rulebase|network interface|vsys|shared)\b", text, re.MULTILINE)
            or re.search(r"^\s*(deviceconfig|rulebase)\s*\{", text, re.MULTILINE)
            or (re.search(r"^config (system|firewall|router|vpn|user|log)\b", text, re.MULTILINE)
                and re.search(r"^end\s*$", text, re.MULTILINE))):
        return UNSUPPORTED
    set_lines = len(re.findall(r"^set (system|interfaces|protocols|security|policy-options|routing-options|snmp)\b",
                               text, re.MULTILINE))
    if set_lines >= 2 or re.search(r"^(system|interfaces)\s*\{", text, re.MULTILINE):
        return "junos"
    if re.search(r"^feature \S+", text, re.MULTILINE) or "!Command: show running-config" in text:
        return "nxos"
    if (re.search(r"^management (api http-commands|telnet|ssh|console|security)\b", text, re.MULTILINE)
            or re.search(r"^daemon TerminAttr", text, re.MULTILINE)
            or re.search(r"^service routing protocols model\b", text, re.MULTILINE)
            or re.search(r"^enable password sha512\b", text, re.MULTILINE)
            or re.search(r"^! device: .*\bEOS", text, re.MULTILINE)
            or re.search(r"^interface Ethernet\d+(/\d+)*\s*$", text, re.MULTILINE)):
        return "eos"
    return "ios"


def _parse_blocks(config_text: str) -> "list[tuple[str, int, list]]":
    """Group indented lines under the nearest unindented parent line.

    A hand-rolled, stdlib-only stand-in for the hierarchical parsing
    services/oncall-agent/src/domains/analysis.py does with ciscoconfparse.
    Returns [(parent_text, parent_line_no, [(child_text, child_line_no), ...]), ...].
    """
    blocks: "list[tuple[str, int, list]]" = []
    current = None
    for i, raw in enumerate(config_text.splitlines(), 1):
        if not raw.strip():
            continue
        if raw[:1] in (" ", "\t"):
            if current is not None:
                current[2].append((raw.strip(), i))
        else:
            current = (raw.strip(), i, [])
            blocks.append(current)
    return blocks


def _blocks_matching(blocks, pattern: str):
    return [b for b in blocks if re.match(pattern, b[0], re.IGNORECASE)]


# --- shared IOS-family rules -------------------------------------------------------

def _line_rules(config_text: str) -> "list[dict]":
    findings = []
    for i, line in enumerate(config_text.splitlines(), 1):
        for rule_id, pattern, message, severity in LINE_RULES:
            if re.search(pattern, line, re.IGNORECASE):
                if rule_id == "IOS-002" and re.match(r"^\s*neighbor\s", line, re.IGNORECASE):
                    # A type-7 BGP MD5 key is how IOS stores it once service
                    # password-encryption is on — reversible, but not the plaintext case.
                    findings.append(_f(rule_id, "MEDIUM",
                        f"BGP neighbor password stored as type 7 (reversible)\n      → {line.strip()}", i))
                    continue
                findings.append(_f(rule_id, severity, f"{message}\n      → {line.strip()}", i))
        m = SNMP_COMMUNITY_RE.match(line)
        if m:
            opts = m.group(1).lower().split()
            if "rw" in opts or "network-admin" in opts:
                findings.append(_f("IOS-004", "HIGH",
                    "SNMP community with write access (RW) — anyone with the string can change "
                    f"the config. Remove it; use SNMPv3 with authPriv\n      → {line.strip()}", i))
            else:
                findings.append(_f("IOS-003", "MEDIUM",
                    f"Review SNMP community string security — prefer SNMPv3\n      → {line.strip()}", i))
    return findings


def _line_block_rules(blocks) -> "list[dict]":
    """VTY / console stanza checks (IOS)."""
    findings = []
    for parent_text, parent_line_no, children in _blocks_matching(blocks, r"^line vty\b"):
        has_access_class = False
        for child_text, child_line_no in children:
            if TRANSPORT_TELNET_RE.search(child_text):
                findings.append(_f("IOS-010", "HIGH",
                    f"Telnet enabled on '{parent_text}' — restrict transport input to ssh"
                    f"\n      → {child_text}", child_line_no))
            if child_text.lower().startswith("access-class"):
                has_access_class = True
        if not has_access_class:
            findings.append(_f("IOS-011", "MEDIUM",
                f"'{parent_text}' has no access-class — management access is unrestricted",
                parent_line_no))

    for parent_text, _n, children in _blocks_matching(blocks, r"^line (vty|con|aux)\b"):
        for child_text, child_line_no in children:
            if PLAINTEXT_LINE_PASSWORD_RE.match(child_text):
                findings.append(_f("IOS-012", "HIGH",
                    f"Plaintext password on '{parent_text}' — use a hashed secret or enable "
                    f"service password-encryption\n      → {child_text}", child_line_no))
    return findings


def _bgp_rules(blocks, max_prefix_words=("maximum-prefix",)) -> "list[dict]":
    """IOS/EOS style: `neighbor X remote-as N` anywhere under `router bgp`.

    A neighbor counts as covered if its peer-group or an inherited peer-session /
    peer-policy template carries the password or the limit. Names keep their case:
    peer-group and template names are case-sensitive on the box.
    """
    findings = []
    for _parent, _n, children in _blocks_matching(blocks, r"^router bgp\b"):
        peers: "dict[str, int]" = {}
        inherits: "dict[str, set]" = {}
        has_password: "set[str]" = set()
        has_limit: "set[str]" = set()
        template = None
        for text, line_no in children:
            low = text.lower()
            t = re.match(r"^template peer-(?:session|policy)\s+(\S+)", text, re.IGNORECASE)
            if t:
                template = "template:" + t.group(1)
                continue
            if low.startswith(("exit-peer-session", "exit-peer-policy")):
                template = None
                continue
            if template and not low.startswith("neighbor"):
                if low.startswith("password"):
                    has_password.add(template)
                elif low.split()[0] in max_prefix_words:
                    has_limit.add(template)
                continue
            m = re.match(r"^neighbor\s+(\S+)\s+(.*)$", text, re.IGNORECASE)
            if not m:
                continue
            peer, rest = m.group(1), m.group(2)
            words = rest.split()
            first = words[0].lower()
            if first == "remote-as":
                peers.setdefault(peer, line_no)
            elif first == "peer-group" and len(words) >= 2:          # neighbor X peer-group NAME
                inherits.setdefault(peer, set()).add(words[1])
            elif rest.lower().startswith("peer group ") and len(words) >= 3:  # EOS: peer group NAME
                inherits.setdefault(peer, set()).add(words[2])
            elif first == "inherit" and len(words) >= 3:             # inherit peer-session NAME
                inherits.setdefault(peer, set()).add("template:" + words[2])
            elif first == "password":
                has_password.add(peer)
            elif first in max_prefix_words:
                has_limit.add(peer)
        for peer, line_no in peers.items():
            sources = {peer} | inherits.get(peer, set())
            if not sources & has_password:
                findings.append(_f("BGP-001", "MEDIUM",
                    f"BGP neighbor {peer} has no password (TCP MD5/TCP-AO) — sessions can be "
                    "spoofed or reset", line_no))
            if not sources & has_limit:
                findings.append(_f("BGP-002", "MEDIUM",
                    f"BGP neighbor {peer} has no {max_prefix_words[0]} limit — a leak from this "
                    "peer can exhaust the RIB", line_no))
    return findings


def _best_practice_rules(config_text: str) -> "list[dict]":
    lowered = config_text.lower()
    findings = []
    # NX-OS keeps its local log in `logging logfile`, not a buffer.
    if "logging buffered" not in lowered and "logging logfile" not in lowered:
        findings.append(_f("BP-001", "MEDIUM", "Missing 'logging buffered' configuration"))
    if "ntp server" not in lowered:
        findings.append(_f("BP-002", "MEDIUM", "No NTP server configured"))
    if "banner" not in lowered:
        findings.append(_f("BP-003", "LOW", "No login banner configured"))
    return findings


# --- per-vendor ----------------------------------------------------------------------

def _ios_rules(config_text: str, blocks) -> "list[dict]":
    findings = _line_rules(config_text) + _line_block_rules(blocks) + _bgp_rules(blocks)
    lowered = config_text.lower()
    if "enable secret" not in lowered:
        findings.append(_f("IOS-020", "HIGH", "No 'enable secret' configured — privileged access is unprotected"))
    if "service password-encryption" not in lowered or re.search(
            r"^no service password-encryption", config_text, re.MULTILINE | re.IGNORECASE):
        findings.append(_f("IOS-021", "HIGH",
            "service password-encryption not enabled — stored passwords are plaintext"))
    if "aaa new-model" not in lowered:
        findings.append(_f("IOS-022", "MEDIUM", "No 'aaa new-model' — AAA authentication is not enabled"))
    if not re.search(r"^ip ssh version 2\b", config_text, re.MULTILINE | re.IGNORECASE):
        findings.append(_f("IOS-023", "MEDIUM",
            "No 'ip ssh version 2' — the device may still accept SSHv1"))
    return findings


def _eos_rules(config_text: str, blocks) -> "list[dict]":
    findings = _line_rules(config_text) + _bgp_rules(blocks, ("maximum-routes", "maximum-prefix"))
    for parent, line_no, children in _blocks_matching(blocks, r"^management telnet\b"):
        if any(c.lower() == "no shutdown" for c, _ in children):
            findings.append(_f("EOS-001", "HIGH", "Telnet management is enabled ('management telnet' / no shutdown)", line_no))
    for parent, line_no, children in _blocks_matching(blocks, r"^management api http-commands\b"):
        if any(re.match(r"^protocol http\b(?!s)", c, re.IGNORECASE) for c, _ in children):
            findings.append(_f("EOS-002", "MEDIUM", "eAPI is served over plain HTTP — use 'protocol https'", line_no))
    for i, line in enumerate(config_text.splitlines(), 1):
        if re.match(r"^username \S+ .*\bnopassword\b", line, re.IGNORECASE):
            findings.append(_f("EOS-003", "HIGH", f"Local user with no password\n      → {line.strip()}", i))
    if not re.search(r"^aaa authentication login\b", config_text, re.MULTILINE | re.IGNORECASE):
        findings.append(_f("EOS-004", "MEDIUM", "No 'aaa authentication login' — only local accounts protect login"))
    return findings


def _nxos_bgp_rules(blocks) -> "list[dict]":
    """NX-OS nests neighbor settings under `neighbor X` sub-blocks."""
    findings = []
    for _parent, _n, children in _blocks_matching(blocks, r"^router bgp\b"):
        current = None  # [peer, line_no, has_password, has_limit]
        seen = []
        for text, line_no in children:
            m = re.match(r"^neighbor\s+(\S+)", text, re.IGNORECASE)
            if m:
                current = [m.group(1), line_no, False, False]
                seen.append(current)
                continue
            if re.match(r"^(vrf|template)\b", text, re.IGNORECASE):
                current = None
            elif current is not None:
                if text.lower().startswith("password"):
                    current[2] = True
                elif text.lower().startswith("maximum-prefix") or text.lower().startswith("inherit peer"):
                    current[3] = True
                    if text.lower().startswith("inherit peer"):
                        current[2] = True  # template assumed to carry it; can't see it here
        for peer, line_no, has_pw, has_limit in seen:
            if not has_pw:
                findings.append(_f("BGP-001", "MEDIUM", f"BGP neighbor {peer} has no password", line_no))
            if not has_limit:
                findings.append(_f("BGP-002", "MEDIUM", f"BGP neighbor {peer} has no maximum-prefix limit", line_no))
    return findings


def _nxos_rules(config_text: str, blocks) -> "list[dict]":
    findings = _line_rules(config_text) + _nxos_bgp_rules(blocks)
    for i, line in enumerate(config_text.splitlines(), 1):
        s = line.strip()
        if re.match(r"^feature telnet\b", s, re.IGNORECASE):
            findings.append(_f("NXOS-001", "HIGH", f"Telnet server enabled — use SSH only\n      → {s}", i))
        elif re.match(r"^no password strength-check\b", s, re.IGNORECASE):
            findings.append(_f("NXOS-002", "MEDIUM", f"Password strength check disabled\n      → {s}", i))
        elif re.match(r"^username \S+ password 0 ", s, re.IGNORECASE):
            findings.append(_f("NXOS-003", "HIGH", f"Local user password stored as clear text (type 0)\n      → {s}", i))
    for _p, line_no, children in _blocks_matching(blocks, r"^line vty\b"):
        if not any(c.lower().startswith("access-class") for c, _ in children):
            findings.append(_f("IOS-011", "MEDIUM", "'line vty' has no access-class — management access is unrestricted", line_no))
    return findings


def _junos_rules(config_text: str) -> "list[dict]":
    findings = []
    lines = config_text.splitlines()
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if re.match(r"^set system services telnet\b", s) or s == "telnet;":
            findings.append(_f("JUN-001", "HIGH", f"Telnet service enabled — use SSH only\n      → {s}", i))
        elif re.match(r"^set system services ftp\b", s) or s == "ftp;":
            findings.append(_f("JUN-002", "MEDIUM", f"FTP service enabled\n      → {s}", i))
        elif "plain-text-password-value" in s:
            findings.append(_f("JUN-003", "HIGH", f"Plain-text password stored in the config\n      → {s[:60]}", i))
        elif re.match(r"^set snmp community \S+ authorization read-write\b", s) or s == "authorization read-write;":
            findings.append(_f("JUN-004", "HIGH", f"SNMP community with read-write access\n      → {s}", i))
        elif re.match(r"^set system services ssh root-login allow\b", s) or s == "root-login allow;":
            findings.append(_f("JUN-005", "MEDIUM", f"SSH root login allowed — use 'root-login deny'\n      → {s}", i))
    if "root-authentication" not in config_text:
        findings.append(_f("JUN-006", "HIGH", "No 'system root-authentication' — root has no password set"))
    if not re.search(r"\bntp\b.*\bserver\b|^\s*server \S+;", config_text, re.MULTILINE):
        findings.append(_f("JUN-007", "MEDIUM", "No NTP server configured"))

    # BGP: set protocols bgp group G neighbor N ...; authentication-key on group or neighbor.
    groups_with_auth = set(re.findall(r"^set protocols bgp group (\S+) authentication-key\b", config_text, re.MULTILINE))
    neighbors_with_auth = set(re.findall(r"^set protocols bgp group \S+ neighbor (\S+) authentication-key\b",
                                         config_text, re.MULTILINE))
    seen = set()
    for i, line in enumerate(lines, 1):
        m = re.match(r"^set protocols bgp group (\S+) neighbor (\S+)", line.strip())
        if m and m.group(2) not in seen:
            seen.add(m.group(2))
            if m.group(1) not in groups_with_auth and m.group(2) not in neighbors_with_auth:
                findings.append(_f("BGP-001", "MEDIUM", f"BGP neighbor {m.group(2)} has no authentication-key", i))
    return findings


def audit_detailed(config_text: str, check_type: str = "all", vendor: str = "") -> "list[dict]":
    """Return [{rule_id, severity, message, line}] — line 0 for whole-config findings."""
    vendor = vendor or detect_vendor(config_text)
    if vendor not in VENDORS:
        return []
    blocks = _parse_blocks(config_text)
    findings: "list[dict]" = []

    if check_type in ("security", "all"):
        if vendor == "junos":
            findings += _junos_rules(config_text)
        elif vendor == "eos":
            findings += _eos_rules(config_text, blocks)
        elif vendor == "nxos":
            findings += _nxos_rules(config_text, blocks)
        else:
            findings += _ios_rules(config_text, blocks)

    if check_type in ("best_practices", "all") and vendor != "junos":
        findings += _best_practice_rules(config_text)

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["line"]))
    return findings


def unsupported_message() -> str:
    return ("Vendor not recognised (FortiOS, PAN-OS and IOS-XR have no local audit rules yet). "
            "Nothing was checked — review this config manually, or pass --vendor ios|nxos|eos|junos "
            "if the detection is wrong.")


def audit(config_text: str, check_type: str = "all", vendor: str = "") -> "list[tuple[str, str, int]]":
    """Return [(severity, message, line_no)] — the shape the MCP server consumes."""
    return [(f["severity"], f"{f['rule_id']}: {f['message']}", f["line"])
            for f in audit_detailed(config_text, check_type, vendor)]


def main() -> None:
    p = argparse.ArgumentParser(
        prog="audit_config",
        description="Regex security audit of a network device config. Runs locally — "
                    "config text never leaves this machine.",
    )
    p.add_argument("file", nargs="?", default="-",
                   help="config file path, or '-' to read stdin (default)")
    p.add_argument("--check-type", default="all",
                   choices=["security", "best_practices", "all"])
    p.add_argument("--vendor", default="", choices=("",) + VENDORS,
                   help="override vendor detection")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()

    if args.file == "-":
        text = sys.stdin.read()
    else:
        path = Path(args.file)
        if not path.is_file():
            print(f"audit_config: no such file: {args.file}", file=sys.stderr)
            sys.exit(1)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"audit_config: cannot read {args.file}: {exc}", file=sys.stderr)
            sys.exit(1)

    if not text.strip():
        print("audit_config: empty configuration input", file=sys.stderr)
        sys.exit(1)

    vendor = args.vendor or detect_vendor(text)
    findings = audit_detailed(text, args.check_type, vendor)
    if vendor not in VENDORS and not args.json:
        print(unsupported_message())
        return
    if args.json:
        print(json.dumps({"vendor": vendor, "findings": findings}, indent=2))
        return
    if not findings:
        print("No issues found in configuration analysis.")
        return

    print(f"Config Analysis Results ({len(findings)} issues found, vendor: {vendor}):\n")
    for f in findings:
        where = f"Line {f['line']}: " if f["line"] else ""
        print(f"[{f['severity']}] {f['rule_id']} {where}{f['message']}\n")


if __name__ == "__main__":
    main()
