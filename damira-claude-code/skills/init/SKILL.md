---
name: init
description: Set up the current folder as a Damira network-operations workspace — configs/, documents/ and notes/ folders, plus project instructions describing the engineer's network. Run once per project; re-running updates the answers.
disable-model-invocation: true
argument-hint: "[vendors, platforms and versions, environment — or leave blank to be asked]"
allowed-tools: Bash, AskUserQuestion
---

# Set up a Damira workspace

Sets up the current working directory. Existing files are safe: `init` only
writes inside its own marked block of CLAUDE.md, and only creates a README or
folders that aren't there yet.

## Step 1: Get the answers

If the user passed details after the command, use them and skip to step 2.

Otherwise ask with AskUserQuestion, in a single call:
- **Vendors** (multiSelect): Cisco, Juniper, Arista, Palo Alto, Fortinet
- **Environment**: production, lab, both
- **Change management**: ITIL with a CAB, lightweight peer review, none
- **Ticketing**: ServiceNow, Jira, none

Then ask once, in plain text, for the key platforms and versions, e.g.
"Core switches: Catalyst 9300, IOS-XE 17.9.4". Say it's optional. Don't
invent platforms or versions the user didn't give.

Then ask about the ecosystem, in one more AskUserQuestion call. Skip any
category the user doesn't use:
- **~~itsm** (change and incident records): ServiceNow, Jira Service
  Management, Freshservice, none. Follow up in plain text for the assignment
  group or project, e.g. "NetOps".
- **~~tracker** (follow-up tasks): Jira, monday, Linear, none. Ask for the
  project key.
- **~~chat** (incident and change notices): Slack, Microsoft Teams, none. Ask
  for the channel.
- **~~paging**: PagerDuty, Opsgenie, none.
- **Default change type**: standard, normal, emergency.

`~~observability`, `~~source-of-truth` and `~~docs` work the same way. Add
them only if the user brings them up. The categories and schemas are in the
plugin's `CONNECTORS.md`. Damira never installs or configures these
connectors. It records which ones the engineer uses.

## Step 2: Run init

The script ships in this plugin, two levels above this skill's base directory:
`<plugin root>/scripts/damira.py`. Build one command, quoting every value,
with one `--vendor` and one `--platform` per item:

```bash
python3 "<plugin root>/scripts/damira.py" init --target claude \
  --vendor "Cisco" --vendor "Palo Alto" \
  --platform "Core switches: Catalyst 9300, IOS-XE 17.9.4" \
  --environment "production" --change-mgmt "ITIL with a CAB" --ticketing "ServiceNow" \
  --ecosystem "itsm=ServiceNow:NetOps" --ecosystem "chat=Slack:#noc-changes" \
  --change-type "normal"
```

Pass one `--ecosystem "CATEGORY=CONNECTOR[:GROUP_OR_KEY]"` per category the
user answered. Leave out any option the user didn't answer.

## Step 3: Report

Show the script's output, then suggest two first prompts that fit their
answers, e.g. an upgrade question for the version they gave and a config audit
of a file in `configs/`. Mention that `configs/` is git-ignored because device
configs carry secrets.

If `configs/` holds device configs, one first prompt can be "draw the topology"
(the generate-diagram skill), best with saved `show cdp neighbors detail` output.
