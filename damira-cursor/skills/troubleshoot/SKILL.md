---
name: troubleshoot
description: Ask Damira to diagnose an active, in-progress network fault. Use when the user reports something broken right now — an outage, a flapping interface, a BGP or OSPF adjacency down, dropped or blackholed traffic, failed calls, users unable to connect — or pastes show/log output for analysis. Returns vendor-specific diagnosis with exact CLI commands. Do NOT use for "how does X work" protocol questions, for reviewing a config that is not currently broken (use config-audit), or for planning an upgrade (use upgrade-plan).
---

# Network Troubleshooting

Diagnose network issues the way a CCIE would: gather evidence, isolate the fault domain,
rank the likely causes, then resolve and prevent a repeat.

## Step 1: Gather

Ask for:
- **Problem description** — what's broken, when it started, what changed
- **Platform** — Cisco IOS-XE, Arista EOS, Palo Alto PAN-OS, Juniper Junos, etc.
- **Show output** — anything relevant they can paste

If they've already given you this, skip to Step 2.

## Step 2: Get the diagnosis

```bash
~/.damira/bin/damira troubleshoot \
  "<problem description>" \
  --platform "<platform>" \
  --show-output "<pasted output>"
```

For long output, pipe it instead:

```bash
cat /path/to/output.txt | ~/.damira/bin/damira troubleshoot \
  "<problem description>" --platform "<platform>" --show-output -
```

**You must run this.** Do not diagnose from your own knowledge — Damira returns
vendor-specific diagnosis with exact CLI commands that go beyond training data.

**If the command exits non-zero, stop.** That is not a diagnosis. Report what it said
and offer to retry. Do not fall back to your own recollection and present it as though
it were verified.

## Step 3: Present findings

1. **Problem summary** — one sentence
2. **Root cause analysis** — what the data shows
3. **Differential diagnoses** — 3+ possible causes, most probable first
4. **Diagnostic commands** — exact CLI, in code blocks, for the engineer to run
5. **Recommended fix** — specific commands per probable cause
6. **Verification** — how to confirm the fix worked

## Step 4: Iterate

When the engineer pastes more output, run `troubleshoot` again — but **each call is
independent and remembers nothing from the previous one.**

Send the *cumulative* picture every time:
- the problem statement plus everything learned so far
- **all** output collected this session, earlier turns included — not just the newest paste

Sending only the delta makes the second diagnosis worse than the first despite having
more evidence, because the call loses the original symptoms.

## Step 5: Document

Once resolved, offer:

> "Want me to write an incident report? I'll save it to `documents/`."

If yes, read `references/incident-report.md` for the required sections, write the full
report filling in every one, and save to `documents/incident-report-{date}.md`.

Then offer a Word copy: `~/.damira/bin/damira docx documents/incident-report-{date}.md`
writes the `.docx` and a self-contained `.html` preview next to it (no install needed).
Open the preview in Cursor's browser. Before sharing it outside this machine, re-run with
`--redact --out-dir documents/share`. Exit code 4 means no python-docx and no uv: suggest
installing uv, and ask before using `--remote`, which uploads the report.

For a reusable runbook covering this failure mode, `references/runbook.md` has that
structure.

To show the affected devices and links, offer to draw the topology from `configs/`
with the generate-diagram skill (`../generate-diagram/SKILL.md`) and reference
`topology.svg` in the report.

## Device access

Advisor mode is the default: present the diagnostic commands for the engineer to run and
take their pasted output. Do not offer to SSH. See the Damira rule for the full posture.
