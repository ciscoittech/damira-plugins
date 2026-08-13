---
name: config-audit
description: Security-audit an existing network device configuration — router, switch, firewall, wireless controller — for weak credentials, insecure management access, missing hardening, and best-practice violations. Use when the user pastes a device config or points at a .cfg file and asks to review, audit, harden, or check it. Not for writing a new config (use generate-config) and not for diagnosing an active outage (use troubleshoot).
paths: ["configs/**", "**/*.cfg", "**/*.conf"]
---

# Configuration Security Audit

Audit network device configurations for security vulnerabilities and best-practice
violations.

## Step 1: Get the config

- **File reference** — the user points at a file (`@configs/router.cfg`). Use the path.
- **Paste** — the user pastes config text. Write it to a temp file, or pipe it in.

Auditing a directory: audit each `.cfg` / `.conf` file individually.

## Step 2: Run the audit

```bash
~/.damira/bin/damira-audit-config configs/router.cfg
```

Or from stdin:

```bash
cat configs/router.cfg | ~/.damira/bin/damira-audit-config -
```

Optionally `--check-type security` or `--check-type best_practices` to narrow it;
the default is `all`.

**You must run this.** Do not review the config only by eye — the script catches specific
patterns (type 7 passwords, SNMP communities, HTTP management, missing NTP, missing
logging, missing banner) with consistent severity ratings.

**This runs entirely on the engineer's machine.** Config text is never sent anywhere.
Say so if they ask — it is a real differentiator, not a footnote.

## Step 3: Present findings

Group by severity:

**HIGH** — each finding with line number, issue, and the exact remediation command
**MEDIUM** — each finding with recommendation
**LOW / INFORMATIONAL** — table

## Step 4: Remediation

For each finding, give the **exact vendor-specific CLI command** to fix it. If you are
not certain of the syntax for that platform and version:

```bash
~/.damira/bin/damira search-vendor-docs \
  "<feature> configuration <platform> <version>" --vendor "<vendor>"
```

If that exits non-zero, say the lookup failed rather than guessing at syntax the engineer
will paste into a production device.

## Step 5: Report (optional)

If several configs were audited, offer to save `documents/config-audit-{date}.md` with a
summary table (device, findings by severity), detailed findings per device, and the
remediation commands.
