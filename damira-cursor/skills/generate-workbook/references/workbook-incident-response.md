# Incident response workbook

Use for a post-incident workbook: timeline plus corrective actions.

**Shape:** Timeline / Action Items. This is the one workbook that is not three phases
(baselines, the work, verification): it records what happened and what gets fixed.

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
- Timeline rows come from the troubleshoot session and the engineer's pasted output. Action-item owners and due dates are input cells.

## Example spec
The example below is illustrative structure. Replace every value with the user's
environment and the evidence. Don't copy its commands.

```json
{
  "title": "Post-Mortem — WAN Outage 2026-03-15",
  "summary_fields": {
    "Incident": "WAN link failure — MPLS PE router",
    "Duration": "47 minutes",
    "Impact": "Branch offices lost connectivity",
    "Lead": "[YOUR NAME]"
  },
  "executive_summary": "MPLS PE router BGP session dropped due to MTU mismatch after provider maintenance. Failover to backup link delayed by stale static routes.",
  "sheets": [
    {
      "name": "Timeline",
      "headers": [
        "Time",
        "Event",
        "Who",
        "Impact"
      ],
      "rows": [
        {
          "time": "14:32",
          "event": "Provider begins maintenance on PE link",
          "who": "ISP NOC",
          "impact": "None — maintenance window communicated"
        },
        {
          "time": "14:47",
          "event": "BGP session drops on pe-r1 (MTU mismatch after provider change)",
          "who": "Auto-detect",
          "impact": "Primary path down"
        },
        {
          "time": "14:49",
          "event": "NOC alert fires — WAN latency spike",
          "who": "Monitoring",
          "impact": "Branch offices impacted"
        },
        {
          "time": "15:02",
          "event": "Engineer identifies stale static route blocking failover",
          "who": "On-call engineer",
          "impact": "Backup path not taking traffic"
        },
        {
          "time": "15:08",
          "event": "Static route removed, traffic fails over",
          "who": "On-call engineer",
          "impact": "Service restored via backup"
        },
        {
          "time": "15:19",
          "event": "Provider confirms MTU restored, primary BGP re-establishes",
          "who": "ISP NOC",
          "impact": "Full restoration"
        }
      ]
    },
    {
      "name": "Action Items",
      "headers": [
        "#",
        "Action",
        "Owner",
        "Due",
        "Status"
      ],
      "rows": [
        {
          "action": "Remove stale static routes from all PE routers",
          "owner": "[ASSIGN]",
          "due": "[DATE]"
        },
        {
          "action": "Add MTU monitoring to BGP peer health checks",
          "owner": "[ASSIGN]",
          "due": "[DATE]"
        },
        {
          "action": "Update runbook with failover validation steps",
          "owner": "[ASSIGN]",
          "due": "[DATE]"
        }
      ],
      "input_columns": [
        "Owner",
        "Due",
        "Status"
      ],
      "dropdowns": {
        "Status": "Open,In Progress,Done"
      },
      "conditional_rules": [
        {
          "column": "Status",
          "type": "status"
        }
      ],
      "auto_id_prefix": "A"
    }
  ]
}
```
