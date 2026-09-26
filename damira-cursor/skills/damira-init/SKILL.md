---
name: damira-init
description: Set up the current folder as a Damira network-operations workspace — configs/, documents/ and notes/ folders, plus an AGENTS.md describing the engineer's network. Use only when the user asks to set up, initialise or bootstrap a Damira workspace or project.
---

# Set up a Damira workspace

Sets up the current project folder. Existing files are safe: `init` only writes
inside its own marked block of AGENTS.md, and only creates a README or folders
that aren't there yet.

## Step 1: Get the answers

If the user already gave details, use them. Otherwise ask, in one message:
- which vendors they run (Cisco, Juniper, Arista, Palo Alto, Fortinet)
- production, lab, or both
- how changes are approved (ITIL with a CAB, peer review, none) and what
  ticketing they use
- optionally, key platforms and versions, e.g. "Core switches: Catalyst 9300,
  IOS-XE 17.9.4"
- which ecosystem tools they use, per category, skipping any they don't:
  `~~itsm` (ServiceNow, Jira Service Management, Freshservice) with the
  assignment group or project; `~~tracker` (Jira, monday, Linear) with the
  project key; `~~chat` (Slack, Microsoft Teams) with the channel; `~~paging`
  (PagerDuty, Opsgenie); and the default change type (standard, normal,
  emergency)

The categories and record schemas are in the plugin's `CONNECTORS.md`. Damira
records which connectors the engineer uses. It doesn't install them.

Don't invent platforms or versions the user didn't give.

## Step 2: Run init

Quote every value; one `--vendor` and one `--platform` per item. Leave out
anything unanswered.

```bash
~/.damira/bin/damira init --target cursor \
  --vendor "Cisco" --vendor "Palo Alto" \
  --platform "Core switches: Catalyst 9300, IOS-XE 17.9.4" \
  --environment "production" --change-mgmt "ITIL with a CAB" --ticketing "ServiceNow" \
  --ecosystem "itsm=ServiceNow:NetOps" --ecosystem "chat=Slack:#noc-changes" \
  --change-type "normal"
```

One `--ecosystem "CATEGORY=CONNECTOR[:GROUP_OR_KEY]"` per category answered.

## Step 3: Report

Show the output, then suggest two first prompts that fit their answers.
Mention that `configs/` is git-ignored because device configs carry secrets.

If `configs/` holds device configs, one first prompt can be "draw the topology"
(the generate-diagram skill), best with saved `show cdp neighbors detail` output.
