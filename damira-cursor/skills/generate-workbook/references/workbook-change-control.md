# Change control workbook

Use for a standard or normal change with CAB fields, implementation, and backout.

**Shape:** Pre-Change / Implementation / Post-Change. Every procedure workbook follows the same three phases:
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
- RFC fields (change number, CAB date, approver) are placeholders the engineer fills in. Never make them up.

## Example spec
The example below is illustrative structure. Replace every value with the user's
environment and the evidence. Don't copy its commands.

```json
{
  "title": "Change Control — Nexus 9300 to 9500 Replacement",
  "summary_fields": {
    "Change ID": "[CHG-XXXX]",
    "Requester": "[YOUR NAME]",
    "Window": "[DATE TIME - TIME]",
    "Impact": "Core switch replacement — 15 min traffic outage"
  },
  "executive_summary": "Replace Nexus 9300 with 9500 in core. Migrate config, verify OSPF/BGP adjacency, validate traffic.",
  "sheets": [
    {
      "name": "Pre-Checks",
      "headers": [
        "#",
        "Check",
        "CLI Command",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "check": "Capture OSPF neighbors",
          "cli_command": "show ip ospf neighbors",
          "expected_result": "All neighbors FULL — record list",
          "what_you_need": "Device IP, SSH creds"
        },
        {
          "check": "Capture BGP peers",
          "cli_command": "show ip bgp summary",
          "expected_result": "All peers Established — record list",
          "what_you_need": "Device IP, SSH creds"
        },
        {
          "check": "Capture route count",
          "cli_command": "show ip route summary",
          "expected_result": "Record total routes",
          "what_you_need": "Device IP"
        },
        {
          "check": "Capture interface counters",
          "cli_command": "show interface counters",
          "expected_result": "Record for comparison",
          "what_you_need": "Device IP"
        },
        {
          "check": "Save running config",
          "cli_command": "copy running-config bootflash:pre-change-backup.cfg",
          "expected_result": "Config saved",
          "what_you_need": "Device IP, SSH creds"
        },
        {
          "check": "Verify new switch config staged",
          "cli_command": "show running-config",
          "expected_result": "Config matches migration plan",
          "what_you_need": "New switch IP, config file"
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
        "Action",
        "CLI Command",
        "Expected Result",
        "Rollback",
        "What You Need",
        "Status"
      ],
      "rows": [
        {
          "action": "Drain traffic from old switch",
          "cli_command": "router ospf 1\n max-metric router-lsa",
          "expected_result": "Traffic shifts to alternate path",
          "rollback": "no max-metric router-lsa",
          "what_you_need": "Device IP, SSH creds"
        },
        {
          "action": "Verify traffic drained",
          "cli_command": "show interface ethernet1/1-4 | include rate",
          "expected_result": "Near-zero input and output rate on old switch uplinks",
          "rollback": "N/A",
          "what_you_need": "Device IP"
        },
        {
          "action": "Shutdown old switch uplinks",
          "cli_command": "interface ethernet1/1-4\n shutdown",
          "expected_result": "Switch isolated",
          "rollback": "interface ethernet1/1-4\n no shutdown",
          "what_you_need": "Device IP, interface list"
        },
        {
          "action": "Cable new switch",
          "cli_command": "Manual: physical install",
          "expected_result": "LEDs active, links up",
          "rollback": "Re-cable old switch",
          "what_you_need": "Physical access, cabling plan"
        },
        {
          "action": "Apply config to new switch",
          "cli_command": "copy bootflash:migration.cfg running-config",
          "expected_result": "Config loaded",
          "rollback": "Power off new, reconnect old",
          "what_you_need": "New switch console, config file"
        },
        {
          "action": "Enable uplinks",
          "cli_command": "interface ethernet1/1-4\n no shutdown",
          "expected_result": "Links come up",
          "rollback": "interface ethernet1/1-4\n shutdown",
          "what_you_need": "New switch IP"
        },
        {
          "action": "Verify OSPF adjacency",
          "cli_command": "show ip ospf neighbors",
          "expected_result": "All neighbors FULL",
          "rollback": "Check config, rollback if needed",
          "what_you_need": "New switch IP"
        },
        {
          "action": "Remove max-metric",
          "cli_command": "router ospf 1\n no max-metric router-lsa",
          "expected_result": "Traffic returns to new switch",
          "rollback": "Re-apply max-metric",
          "what_you_need": "New switch IP"
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
      "auto_id_prefix": "I"
    },
    {
      "name": "Post-Checks",
      "headers": [
        "#",
        "Check",
        "CLI Command",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "check": "OSPF neighbors match pre-change",
          "cli_command": "show ip ospf neighbors",
          "expected_result": "Same neighbor list as Pre-Change",
          "what_you_need": "Baseline from Pre-Change"
        },
        {
          "check": "BGP peers match pre-change",
          "cli_command": "show ip bgp summary",
          "expected_result": "Same peer list, all Established",
          "what_you_need": "Baseline from Pre-Change"
        },
        {
          "check": "Route count matches",
          "cli_command": "show ip route summary",
          "expected_result": "Same total routes as Pre-Change",
          "what_you_need": "Baseline from Pre-Change"
        },
        {
          "check": "Traffic flowing through new switch",
          "cli_command": "show interface counters errors",
          "expected_result": "Active traffic on uplinks",
          "what_you_need": "New switch IP"
        },
        {
          "check": "No errors on interfaces",
          "cli_command": "show interface counters errors",
          "expected_result": "Zero errors since cutover",
          "what_you_need": "New switch IP"
        },
        {
          "check": "Save config",
          "cli_command": "copy running-config startup-config",
          "expected_result": "Config saved",
          "what_you_need": "New switch IP, SSH creds"
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
