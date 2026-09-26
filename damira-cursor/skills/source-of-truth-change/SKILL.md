---
name: source-of-truth-change
description: Turn intended state in the engineer's source of truth (NetBox or Nautobot) into a validated change, then hand it to the automation they already run — an Ansible Automation Platform job in check mode, a pyATS/Genie before-and-after diff, or a Terraform plan. Use when the user asks to make a change "from NetBox" or "from Nautobot", to push what the source of truth says, to bring devices in line with intended state, or to run a validated playbook through AAP or pyATS. Damira never applies the change; the engineer does. For a playbook with no source of truth use generate-playbook, for Terraform alone use generate-terraform, and for an active outage use troubleshoot.
---

# Source-of-truth change

Damira orchestrates and hosts nothing. The engineer's own MCP servers read and run:

- `~~source-of-truth`: NetBox or Nautobot, the intended state
- `~~automation`: Ansible Automation Platform, runs a job template (check mode from here)
- `~~testing`: pyATS/Genie, pre and post snapshots and their diff
- `~~iac`: Terraform, provider and module documentation

Find their tools with tool search. The **Automation capabilities** section that
`damira init` wrote to AGENTS.md names the servers it found. If there is no
`~~source-of-truth`, ask the engineer to paste the intended state (devices, VLANs,
prefixes) and start at Step 2.

Advisor mode holds throughout. The plugin's device gate asks the engineer before every AAP
launch (check mode included) and before any pyATS call that reaches a device, and blocks
pyATS config pushes and Terraform runs. A blocked call is an answer, not an obstacle: do not
retry it through another tool or the terminal.

## Step 1: Read the intent

Read `references/netbox-intent.md` (beside this file). Query `~~source-of-truth` for only
the objects in scope, filtered by site or location, role, tag and status: devices with
platform and primary IP, the interfaces, VLANs and prefixes the change touches, and
rendered config context. Never pull the whole inventory.

Show the engineer a short table of the intent (device, object, intended value) with the
object IDs, and get a yes before generating. If the objects contradict each other (a VLAN
assigned to an interface but missing from the site), stop and say which records disagree.
Do not fill gaps from memory.

## Step 2: Generate the change

Use the generator that matches the hand-off, following its steps for vendor lookups,
layout and secrets:

| Hand-off | Generator skill |
|---|---|
| `~~automation` (AAP) or plain Ansible | generate-playbook |
| `~~iac` / Terraform | generate-terraform |
| Python (Nornir, Netmiko) | generate-automation |
| `~~testing` checks only | generate-tests |

Build variables from the Step 1 objects, not from assumptions. If AAP already syncs its
inventory from NetBox, target hosts with a limit instead of writing a static inventory.
Secrets stay as environment or vault lookups; never copy them out of the source of truth.

## Step 3: Validate

**Delegate this loop to the `damira-fixer` subagent** (pinned to a cheap model). Give it
the path and `--skill source-of-truth-change`. It fixes only what the findings name and
stops after 3 rounds. If the subagent isn't available, run it yourself:

```bash
~/.damira/bin/damira validate <path> --skill source-of-truth-change --host cursor
```

Fix every FAIL and re-run, at most 3 rounds. A `skipped` check is not a pass. Nothing that
fails validate goes to a hand-off.

## Step 4: Hand off

Pick every hand-off that was detected, and read its reference first:

- `~~automation`: `references/handoff-aap.md`. Launch the job template with
  `job_type=check` and diff mode on, limited to one host first. Check first that the
  template prompts for job type on launch; if it does not, AAP ignores the check request,
  so do not launch.
- `~~testing`: `references/handoff-pyats.md`. Take the pre-change snapshot of the
  features the change touches; the post snapshot and diff come after the engineer applies.
- `~~iac`: `references/handoff-terraform.md`. The plan runs locally or in the engineer's
  pipeline; the Terraform server is for documentation lookups only.
- None detected: give the engineer the commands instead, e.g.
  `ansible-playbook -i <inventory> <playbook> --check --diff --limit <one-host>`.

## Step 5: Report

Present, in this order:

1. Intent: the source-of-truth filter used and the object IDs.
2. Files written and what validate reported (pass, warnings, skipped tools).
3. Hand-off result: the check-mode diff summary, the pyATS pre snapshot, or the plan summary.
4. The exact command or job the engineer runs to apply, and the rollback.

Offer to draft the `~~itsm` change request from the plugin's `CONNECTORS.md`, with the
validate output as `validate_report`. Write it with the engineer's connector only after
they confirm.
