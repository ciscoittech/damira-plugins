# Migration workbook

Use for moving a service between hardware or sites on the same platform family (router refresh, DC move, circuit cutover).

**Shape:** Pre-Checks / Cutover Steps / Post-Checks. Every procedure workbook follows the same three phases:
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
- Keep before/after identifiers (old device, new device, circuit IDs) in input columns the engineer fills in. Don't invent them.

## Example spec
The example below is illustrative structure. Replace every value with the user's
environment and the evidence. Don't copy its commands.

```json
{
  "title": "BGP AS Migration — 65000 to 65100",
  "summary_fields": {
    "Migration Type": "BGP AS Number",
    "Current AS": "65000",
    "Target AS": "65100",
    "Devices": "4 core routers",
    "Engineer": "[YOUR NAME]",
    "Maintenance Window": "[DATE TIME - TIME]"
  },
  "executive_summary": "Migrate BGP AS number from 65000 to 65100 across 4 core routers using local-as. Zero-downtime approach with per-peer cutover.",
  "sheets": [
    {
      "name": "Pre-Checks",
      "headers": [
        "#",
        "Device",
        "Check",
        "CLI Command",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "device": "core-r1",
          "check": "BGP neighbor state",
          "cli_command": "show ip bgp summary",
          "expected_result": "All peers Established",
          "what_you_need": "Device IP, SSH creds"
        },
        {
          "device": "core-r1",
          "check": "Route count baseline",
          "cli_command": "show ip bgp summary | include Total",
          "expected_result": "Record count",
          "what_you_need": "Device IP"
        },
        {
          "device": "core-r1",
          "check": "Save running config",
          "cli_command": "copy running-config startup-config",
          "expected_result": "Config saved",
          "what_you_need": "Device IP, SSH creds"
        },
        {
          "device": "ALL",
          "check": "Verify no active maintenance",
          "cli_command": "Manual: check NOC calendar",
          "expected_result": "No conflicting changes",
          "what_you_need": "NOC calendar access"
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
      "auto_id_prefix": "P"
    },
    {
      "name": "Implementation Steps",
      "headers": [
        "#",
        "Device",
        "Action",
        "CLI Command",
        "Expected Result",
        "Rollback",
        "What You Need",
        "Status"
      ],
      "rows": [
        {
          "device": "core-r1",
          "action": "Add local-as to each peer",
          "cli_command": "neighbor [NEIGHBOR IP] local-as 65100 no-prepend replace-as",
          "expected_result": "Peer re-establishes with AS 65100",
          "rollback": "no neighbor [NEIGHBOR IP] local-as",
          "what_you_need": "Peer IPs, new AS number"
        },
        {
          "device": "core-r1",
          "action": "Verify peer re-established",
          "cli_command": "show ip bgp neighbors [NEIGHBOR IP] | i local AS",
          "expected_result": "Local AS 65100",
          "rollback": "N/A",
          "what_you_need": "Peer IPs"
        },
        {
          "device": "core-r1",
          "action": "Verify route count stable",
          "cli_command": "show ip bgp summary | include Total",
          "expected_result": "Count matches baseline",
          "rollback": "Remove local-as if count drops",
          "what_you_need": "Baseline from Pre-Check"
        },
        {
          "device": "core-r2",
          "action": "Repeat: Add local-as to peers",
          "cli_command": "neighbor [NEIGHBOR IP] local-as 65100 no-prepend replace-as",
          "expected_result": "Peers re-establish",
          "rollback": "no neighbor [NEIGHBOR IP] local-as",
          "what_you_need": "Peer IPs, new AS number"
        }
      ],
      "input_columns": [
        "Status"
      ],
      "dropdowns": {
        "Status": "Not Started,Done,Failed,Rolled Back"
      },
      "conditional_rules": [
        {
          "column": "Status",
          "type": "status"
        }
      ],
      "auto_id_prefix": "C"
    },
    {
      "name": "Post-Checks",
      "headers": [
        "#",
        "Device",
        "Check",
        "CLI Command",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "device": "ALL",
          "check": "All peers show new AS",
          "cli_command": "show ip bgp summary",
          "expected_result": "AS 65100 on all peers",
          "what_you_need": "All device IPs"
        },
        {
          "device": "ALL",
          "check": "Route counts match baseline",
          "cli_command": "show ip bgp summary | include Total",
          "expected_result": "Matches pre-cutover count",
          "what_you_need": "Baseline from Pre-Check"
        },
        {
          "device": "ALL",
          "check": "No BGP notifications",
          "cli_command": "show ip bgp neighbors [NEIGHBOR IP] | i notification",
          "expected_result": "0 notifications since cutover",
          "what_you_need": "Peer IPs"
        },
        {
          "device": "ALL",
          "check": "Save config",
          "cli_command": "copy running-config startup-config",
          "expected_result": "Config saved",
          "what_you_need": "All device IPs, SSH creds"
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
      "auto_id_prefix": "V"
    }
  ]
}
```
