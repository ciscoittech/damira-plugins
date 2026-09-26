# Security audit workbook

Use for a config or posture audit with findings and remediation tracking.

**Shape:** Pre-Audit / Findings / Remediation Tracking. Every procedure workbook follows the same three phases:
verify readiness and record baselines, do the work step by step, then verify the
result against the baselines.

## Rules for filling it in
- Row keys are the header in lower case with spaces as underscores
  (`"CLI Command"` becomes `cli_command`).
- Anything only the engineer knows (names, IPs, dates, change numbers) is a
  `[BRACKETED PLACEHOLDER]` in an `input_columns` column. Those cells render yellow and
  stay editable.
- Command cells (`CLI Command`, `Command`, `Verification Command`, `Check`) are
  grounding-checked against `documents/<id>/evidence/`. If you can't back a command
  with saved Damira evidence, write `[VERIFY: what to confirm]` rather than guessing.
  The renderer tags any other unbacked command UNVERIFIED.
- `dropdowns` are comma-separated options. `conditional_rules` types: `status`,
  `pass_fail`, `yes_no`, `risk_score`.
- `auto_id_prefix` numbers the first column (`PRE-001`, ...). `formulas` use
  `{Header Name}` placeholders that resolve to that row's cell.
- Findings come from the local config audit (`analyze_config` / `damira-audit-config`) and the CVE lookup. Save both outputs to evidence/ so each finding's check command can be matched.

## Example spec
The example below is illustrative structure. Replace every value with the user's
environment and the evidence. Don't copy its commands.

```json
{
  "title": "Firewall Audit — PA-5260",
  "summary_fields": {
    "Device": "PA-5260 (fw-core-01)",
    "PAN-OS": "11.1.2",
    "Auditor": "[YOUR NAME]"
  },
  "executive_summary": "Security audit of PA-5260 production firewall. Focus on unused rules, overly permissive policies, and cert health.",
  "sheets": [
    {
      "name": "Pre-Audit",
      "headers": [
        "#",
        "Check",
        "Command",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "check": "Record running config hash",
          "command": "show config running",
          "expected_result": "Hash recorded for baseline",
          "what_you_need": "Device IP, admin creds"
        },
        {
          "check": "Export current ruleset",
          "command": "GUI: Panorama > Policies > Export",
          "expected_result": "Ruleset exported to CSV",
          "what_you_need": "Panorama IP, admin creds"
        },
        {
          "check": "Record active sessions count",
          "command": "show session info",
          "expected_result": "Baseline session count",
          "what_you_need": "Device IP"
        }
      ],
      "input_columns": [
        "Actual",
        "Pass?"
      ],
      "dropdowns": {
        "Pass?": "Pass,Fail,N/A"
      },
      "conditional_rules": [
        {
          "column": "Pass?",
          "type": "status"
        }
      ],
      "auto_id_prefix": "A"
    },
    {
      "name": "Findings",
      "headers": [
        "#",
        "Severity",
        "Finding",
        "Affected Rule",
        "Remediation",
        "What You Need",
        "Owner",
        "Status"
      ],
      "rows": [
        {
          "severity": "Critical",
          "finding": "Any-any permit in Trust-to-Untrust zone",
          "affected_rule": "Rule 47",
          "remediation": "Replace with specific service objects",
          "what_you_need": "Service object definitions from app team",
          "owner": "[ASSIGN]"
        },
        {
          "severity": "High",
          "finding": "3 rules with no hit count in 90 days",
          "affected_rule": "Rules 12, 23, 45",
          "remediation": "Disable, monitor 30 days, then delete",
          "what_you_need": "Change control approval",
          "owner": "[ASSIGN]"
        },
        {
          "severity": "Medium",
          "finding": "Wildcard cert expires in 28 days",
          "affected_rule": "N/A",
          "remediation": "Renew with CA, deploy to fw-core-01/02",
          "what_you_need": "CA access, cert request details",
          "owner": "[ASSIGN]"
        }
      ],
      "input_columns": [
        "Owner",
        "Status"
      ],
      "dropdowns": {
        "Severity": "Critical,High,Medium,Low,Info",
        "Status": "Open,In Progress,Resolved,Accepted"
      },
      "conditional_rules": [
        {
          "column": "Status",
          "type": "status"
        }
      ],
      "auto_id_prefix": "F"
    },
    {
      "name": "Remediation Tracking",
      "headers": [
        "#",
        "Check",
        "Command",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "check": "Verify removed rules no longer match",
          "command": "test security-policy-match from trust to untrust source 10.1.1.10 destination 8.8.8.8 protocol 6 destination-port 443",
          "expected_result": "Traffic matches specific rules only",
          "what_you_need": "Device IP, test traffic source"
        },
        {
          "check": "Verify cert renewed",
          "command": "show certificate detail",
          "expected_result": "New expiry date >1 year out",
          "what_you_need": "Device IP"
        },
        {
          "check": "Compare config hash",
          "command": "show config running",
          "expected_result": "Changed from baseline (remediation applied)",
          "what_you_need": "Baseline hash from Pre-Audit"
        }
      ],
      "input_columns": [
        "Actual",
        "Pass?"
      ],
      "dropdowns": {
        "Pass?": "Pass,Fail,N/A"
      },
      "conditional_rules": [
        {
          "column": "Pass?",
          "type": "status"
        }
      ],
      "auto_id_prefix": "R"
    }
  ]
}
```
