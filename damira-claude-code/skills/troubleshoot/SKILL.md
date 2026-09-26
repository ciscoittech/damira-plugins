---
name: troubleshoot
description: Ask Damira to diagnose an active, in-progress network fault. Use when the user reports something broken right now — an outage, a flapping interface, a BGP or OSPF adjacency down, dropped or blackholed traffic, failed calls, users unable to connect — or pastes show/log output for analysis. Returns vendor-specific diagnosis with exact CLI commands. Do NOT use for "how does X work" protocol questions, for reviewing a config that is not currently broken (use config-audit), or for planning an upgrade (use upgrade-plan).
allowed-tools: mcp__plugin_damira_damira__damira_troubleshoot, mcp__plugin_damira_damira__damira_search_vendor_docs, mcp__damira__damira_troubleshoot, mcp__damira__damira_search_vendor_docs
---

# Network Troubleshooting

Diagnose network issues the way a CCIE would: gather evidence, isolate the fault domain, rank the likely causes, then resolve and prevent a repeat.

## Workflow

### Step 1: Gather Information

Ask the user for:
- **Problem description** — what's broken, when it started, what changed
- **Platform** — Cisco IOS-XE, Arista EOS, Palo Alto PAN-OS, Juniper Junos, etc.
- **Show command output** — any relevant output they can paste

If they've already provided this information, skip to Step 2.

### Step 2: Get Diagnosis

Call the `damira_troubleshoot` MCP tool with:
- `problem`: the problem description
- `platform`: the network platform (if known)
- `show_output`: any show command output provided

If the MCP tool isn't available, run the CLI (`<plugin root>` is two levels above this
skill's base directory). Non-zero exit means no diagnosis: report it and stop.

```bash
python3 "<plugin root>/scripts/damira.py" troubleshoot "<problem>" \
  --platform "<platform>" --show-output - < notes/show-output.txt
```

**IMPORTANT:** You MUST call the `damira_troubleshoot` MCP tool (or the CLI above). Do NOT diagnose from your own knowledge — Damira provides vendor-specific diagnosis with exact CLI commands that go beyond training data.

### Step 3: Present Findings

Present the diagnosis clearly:
1. **Problem Summary** — one sentence
2. **Root Cause Analysis** — what the data shows
3. **Differential Diagnoses** — 3+ possible causes, most probable first
4. **Diagnostic Commands** — exact CLI commands for the user to run (in code blocks)
5. **Recommended Fix** — specific commands for each probable cause
6. **Verification** — how to confirm the fix worked

### Step 4: Iterate

If the user provides more show command output, call `damira_troubleshoot` again — but
**each call is independent and remembers nothing from the previous one.**

Send the *cumulative* picture every time, not just the new material:
- `problem` — the original problem statement plus everything learned so far
- `show_output` — all output collected in this session, earlier turns included, not just
  the newest paste

Sending only the delta makes the second diagnosis worse than the first despite having
more evidence, because the tool loses the original symptoms.

### Step 5: Document

Once the issue is resolved, offer:
> "Want me to write an incident report? I'll save it to `documents/`."

If yes:
1. Read `references/incident-report.md` for the required sections
2. Write the full incident report filling in every section
3. Save to `documents/incident-report-{date}.md`
4. Offer a Word copy: `python3 "<plugin root>/scripts/damira.py" docx
   documents/incident-report-{date}.md` writes the `.docx` and a self-contained `.html`
   preview next to it (`<plugin root>` is two levels above this skill's base directory; no
   install needed). Offer the preview in the Browser pane. Before publishing it as an
   artifact, and only if the user says yes, re-run with `--redact --out-dir
   documents/share` and publish the redacted file. Exit code 4 means no python-docx and no
   uv: suggest installing uv, and ask before using `--remote`, which uploads the report.

To show the affected devices and links, offer to draw the topology from `configs/`
with the generate-diagram skill (`../generate-diagram/SKILL.md`) and reference
`topology.svg` in the report.

## SSH Follow-Up

Device access runs through the user's own terminal, using their SSH keys, VPN, and jump
hosts — no credentials pass through Damira.

**Advisor mode is the default, and in advisor mode you do not run commands on devices.**
Present the diagnostic commands in a code block for the user to run, then take their
pasted output. This is the expected path and it is not a limitation to apologise for.

Only when the user has explicitly opted into guided or lab mode may you offer:
> "I can SSH to {device} and run these commands. Want me to?"

If they accept, run `ssh {device} "{command}"` in the terminal, then feed the output back
per Step 4 — cumulatively, with the original problem statement.

Read-only `show` commands only. Never run a configuration change, a `clear` command, a
reload, or anything that alters device state. If the fix requires a change, hand the
engineer the exact commands and let them execute the change themselves.
