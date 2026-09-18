#!/usr/bin/env python3
"""Local network-config security audit — regex, not AI, and deliberately local.

Ported from analyze_config() in services/oncall-mcp/damira_mcp/server.py. It stays on
the engineer's machine on purpose: config text is exactly the material that must not
leave the network, and shipping it to an API to run six regexes would contradict the
PII-and-local-processing posture the product is sold on.

Standard library only — see scripts/damira.py for why.

Exit codes: 0 = audit ran (findings or not), 1 = could not read input.
Findings are not an error; a clean config and a dirty one both exit 0.
"""

import argparse
import re
import sys
from pathlib import Path

SECURITY_PATTERNS = [
    (r"enable password", "Use 'enable secret' instead of 'enable password'", "HIGH"),
    (r"password 7", "Type 7 passwords are trivially reversible", "HIGH"),
    (r"snmp-server community", "Review SNMP community string security — prefer SNMPv3", "MEDIUM"),
    (r"ip http server", "HTTP management is insecure — use HTTPS", "MEDIUM"),
    (r"no service password-encryption", "Enable password encryption", "HIGH"),
    (r"username .* password", "Consider 'secret' instead of 'password'", "MEDIUM"),
]

# Bare "password cisco" / "password 0 cisco" — the plaintext line password used under
# line con/vty/aux. Deliberately excludes "password 7 ..." (already covered above) and
# won't match "enable password ..." or "username ... password ..." since those don't
# start the line with the literal token "password".
PLAINTEXT_LINE_PASSWORD_RE = re.compile(r"^password\s+(?:0\s+)?\S+$", re.IGNORECASE)
TRANSPORT_TELNET_RE = re.compile(r"^transport\s+input\b.*\b(telnet|all)\b", re.IGNORECASE)

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _parse_blocks(config_text: str) -> "list[tuple[str, int, list]]":
    """Group indented lines under the nearest unindented parent line.

    A hand-rolled, stdlib-only stand-in for the hierarchical parsing
    services/oncall-agent/src/domains/analysis.py does with ciscoconfparse (see
    _run_security_checks there for the reference logic this ports). Not imported —
    this plugin has zero cross-service and zero third-party dependencies on purpose.

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


def _block_findings(config_text: str) -> "list[tuple[str, str, int]]":
    """Checks that need to know which 'line' stanza a command sits in."""
    findings: "list[tuple[str, str, int]]" = []
    blocks = _parse_blocks(config_text)

    vty_blocks = [b for b in blocks if re.match(r"^line vty\b", b[0], re.IGNORECASE)]
    for parent_text, parent_line_no, children in vty_blocks:
        has_access_class = False
        for child_text, child_line_no in children:
            if TRANSPORT_TELNET_RE.search(child_text):
                findings.append(("HIGH",
                    f"Telnet enabled on '{parent_text}' — restrict transport input to ssh"
                    f"\n      → {child_text}", child_line_no))
            if child_text.lower().startswith("access-class"):
                has_access_class = True
        if not has_access_class:
            findings.append(("MEDIUM",
                f"'{parent_text}' has no access-class — management access is unrestricted",
                parent_line_no))

    # Plaintext line passwords apply to con/aux too, not just vty — same risk either way.
    line_blocks = [b for b in blocks if re.match(r"^line (vty|con|aux)\b", b[0], re.IGNORECASE)]
    for parent_text, _parent_line_no, children in line_blocks:
        for child_text, child_line_no in children:
            if PLAINTEXT_LINE_PASSWORD_RE.match(child_text):
                findings.append(("HIGH",
                    f"Plaintext password on '{parent_text}' — use a hashed secret or enable "
                    f"service password-encryption\n      → {child_text}", child_line_no))

    return findings


def _whole_config_security_findings(config_text: str) -> "list[tuple[str, str, int]]":
    """Checks that only make sense once, against the whole config, not per line."""
    findings: "list[tuple[str, str, int]]" = []
    lowered = config_text.lower()
    if "enable secret" not in lowered:
        findings.append(("HIGH", "No 'enable secret' configured — privileged access is unprotected", 0))
    if "service password-encryption" not in lowered:
        findings.append(("HIGH",
            "service password-encryption not enabled — stored passwords are plaintext", 0))
    if "aaa new-model" not in lowered:
        findings.append(("MEDIUM", "No 'aaa new-model' — AAA authentication is not enabled", 0))
    return findings


def audit(config_text: str, check_type: str = "all") -> "list[tuple[str, str, int]]":
    """Return [(severity, message, line_no)] — line_no 0 for whole-config findings."""
    findings: "list[tuple[str, str, int]]" = []

    if check_type in ("security", "all"):
        for i, line in enumerate(config_text.splitlines(), 1):
            for pattern, message, severity in SECURITY_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append((severity, f"{message}\n      → {line.strip()}", i))
        findings.extend(_block_findings(config_text))
        findings.extend(_whole_config_security_findings(config_text))

    if check_type in ("best_practices", "all"):
        lowered = config_text.lower()
        if "logging buffered" not in lowered:
            findings.append(("MEDIUM", "Missing 'logging buffered' configuration", 0))
        if "ntp server" not in lowered:
            findings.append(("MEDIUM", "No NTP server configured", 0))
        if "banner" not in lowered:
            findings.append(("LOW", "No login banner configured", 0))

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f[0], 9), f[2]))
    return findings


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

    findings = audit(text, args.check_type)
    if not findings:
        print("No issues found in configuration analysis.")
        return

    print(f"Config Analysis Results ({len(findings)} issues found):\n")
    for severity, message, line_no in findings:
        where = f"Line {line_no}: " if line_no else ""
        print(f"[{severity}] {where}{message}\n")


if __name__ == "__main__":
    main()
