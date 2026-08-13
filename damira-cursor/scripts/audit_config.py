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

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def audit(config_text: str, check_type: str = "all") -> "list[tuple[str, str, int]]":
    """Return [(severity, message, line_no)] — line_no 0 for whole-config findings."""
    findings: "list[tuple[str, str, int]]" = []

    if check_type in ("security", "all"):
        for i, line in enumerate(config_text.splitlines(), 1):
            for pattern, message, severity in SECURITY_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append((severity, f"{message}\n      → {line.strip()}", i))

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
