# Troubleshooting Runbook — required sections

1. **Trigger Conditions** — what symptoms or alerts activate this runbook
2. **Initial Triage** — the first 3 commands to run to assess severity
3. **Diagnostic Decision Tree** — if X then check Y, if Y then check Z
4. **Resolution Procedures** — specific fix for each identified root cause
5. **Escalation Matrix** — L1 → L2 → L3 with SLA timers and contacts
6. **Known Issues & Workarounds** — common false positives and temporary fixes
7. **Related Runbooks** — cross-references for adjacent failure modes

## Quality bar

The decision tree must be specific: "if `show ip bgp summary` shows 0 prefixes received,
check route-map filtering on the inbound policy" — not "check BGP".
