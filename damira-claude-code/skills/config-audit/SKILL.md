---
name: config-audit
description: Security-audit an existing network device configuration — router, switch, firewall, wireless controller — for weak credentials, insecure management access, missing hardening, and best-practice violations. Use when the user pastes a device config or points at a .cfg file and asks to review, audit, harden, or check it. Not for writing a new config (use generate-config) and not for diagnosing an active outage (use troubleshoot).
paths: ["configs/**", "**/*.cfg"]
allowed-tools: mcp__plugin_damira_damira__analyze_config, mcp__plugin_damira_damira__damira_search_vendor_docs, mcp__damira__analyze_config, mcp__damira__damira_search_vendor_docs
---

# Configuration Security Audit

Audit network device configurations for security vulnerabilities and best practice violations.

## Workflow

### Step 1: Get the Config

Two methods:
- **File reference**: User references a file (e.g., `@configs/router.cfg`). Read the file contents.
- **Paste**: User pastes config text directly.

If auditing a directory, read each `.cfg` or `.conf` file and audit them individually.

### Step 2: Run Security Audit

Call the `analyze_config` MCP tool with:
- `config_text`: the full configuration text
- `check_type`: "all" (covers both security and best practices)

If the MCP tool isn't available, run the same local check (`<plugin root>` is two levels
above this skill's base directory; the config never leaves the machine):

```bash
python3 "<plugin root>/scripts/audit_config.py" configs/router.cfg --check-type all
```

**IMPORTANT:** You MUST call the `analyze_config` MCP tool (or the script above). Do NOT just review the config visually — the tool catches specific patterns (type 7 passwords, SNMP communities, HTTP management, missing NTP) with severity ratings.

### Step 3: Present Findings

Format findings by severity:

**CRITICAL / HIGH:**
- List each finding with line number, issue, and remediation command

**MEDIUM:**
- List each finding with recommendation

**LOW / INFORMATIONAL:**
- List in a table

### Step 4: Remediation

For each finding, provide:
- The **exact CLI command** to fix it (vendor-specific)
- Call `damira_search_vendor_docs` if you need platform-specific remediation syntax

### Step 5: Generate Report (Optional)

If multiple configs were audited, offer:
> "Want me to save the audit report to `documents/`?"

Save as `documents/config-audit-{date}.md` with:
- Summary table (device, findings count by severity)
- Detailed findings per device
- Remediation commands
