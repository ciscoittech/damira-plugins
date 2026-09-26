# Damira for Claude Code

CCIE-level network operations inside Claude Code. Damira supplies the domain data: vendor
documentation, CVEs, release-note caveats, structured diagnoses and upgrade assessments.
Claude writes the MOPs, change controls and runbooks from it.

## Install

In Claude Code:

```
/plugin marketplace add ciscoittech/damira-plugins
/plugin install damira@damira-plugins
```

When you enable the plugin, Claude Code asks for three settings:

- **API key**: from [damiraai.com → Dashboard → API Keys](https://damiraai.com/dashboard/api-keys).
  It's stored in your system keychain, not in a settings file. Leave it blank to try Damira
  on the shared demo key (50 queries a day).
- **Execution mode**: leave on `advisor`. Damira recommends the exact commands and you
  run them. `guided` and `lab` let the agent run read-only `show` commands itself and are
  meant for lab gear only.
- **Shell device gate**: `ask` (the default) hands you any `ssh`, `telnet` or `nc` the
  agent wants to run. `strict` blocks them outright.

Needs Python 3 (`python3 --version`). No pip, no uvx: everything runs on the standard
library.

## Set or change your API key

- **Add or replace it:** `/plugin configure damira@damira-plugins`, paste the key, and
  continue through every field until it confirms the save. Run it again to rotate.
- **Scripted:** `claude plugin install damira@damira-plugins --config api_key=oncall_sk_…`
  stores it the same way. Clear your shell history afterwards.
- **Fallbacks when the setting is blank:** an exported `DAMIRA_API_KEY`, then
  `~/.damira/config` (one line: `api_key = oncall_sk_…`). The plugin setting wins over both.

**On the demo key, every answer starts with a note saying so.** If you still see it after
adding your key, the key isn't reaching Damira: run `/plugin configure` again, and make sure
you're on 0.2.6 or later (`/plugin marketplace update damira-plugins`). Before 0.2.6, an
exported `DAMIRA_API_KEY` was ignored whenever the plugin setting was blank.

Full guide: [damiraai.com/docs/install#api-key](https://damiraai.com/docs/install#api-key).

## Set up a project

Run `/damira:init` once in a new project folder. It asks which vendors,
platforms and versions you run and how changes get approved, then creates
`configs/` (kept out of git, since configs carry secrets), `documents/` and
`notes/`, and records your network in `CLAUDE.md` so every chat starts with that
context. Re-running updates your answers without touching the rest of the file.

## What's new in 0.3.2

- **Test a change in a lab first.** The new `lab-test-change` skill deploys a throwaway ContainerLab lab, applies your playbook or script, runs show-command or pyATS/Genie checks, reports pass/fail and always destroys the lab. It needs Docker and containerlab on your machine; without them it validates the change only and says so.
- **`generate-lab` in Claude Code.** Building a ContainerLab topology for practice or testing, previously Cursor-only, is now in the Claude Code plugin too.

## What's new in 0.3.1

- **Source-of-truth changes.** The new `source-of-truth-change` skill turns intended state in NetBox or Nautobot into a validated change, then hands it to the automation you already run: an Ansible Automation Platform job in check mode, a pyATS/Genie before-and-after diff, or a Terraform plan.
- **The device gate covers your orchestration tools.** If you've connected AAP/AWX, pyATS or Terraform MCP servers, read-only calls go through, every AAP job launch asks first, and in advisor mode Terraform apply and pyATS config pushes are blocked (they ask instead in guided or lab mode). `strict` turns every ask into a block.

## What's new in 0.3.0

- **Validated automation.** The playbook, automation, Terraform, test and pipeline generators run `damira validate` on what they write and fix it (up to 3 rounds) before handing it back.
- **Word and Excel deliverables.** MOPs and change controls export to `.docx`, and procedure workbooks to `.xlsx`, each with an HTML preview. Nothing to install: the scripts use python-docx or openpyxl if present, otherwise `uv run --with`.
- **Topology diagrams.** `damira diagram build` reads `configs/` plus CDP/LLDP output; `damira diagram render` draws it. `--redact` writes a copy with hostnames and addresses replaced, for sharing.
- **Cheaper runs.** Mechanical steps (rendering, fixing validation findings) are handed to small agents that run on a cheap model, so premium models are kept for diagnosis.
- **Golden configs.** `damira render` produces NTP, AAA/TACACS+, SNMPv3, syslog and banner baselines for IOS, NX-OS, EOS and Junos.
- **Opt-in usage stats.** `damira stats` shows your local workflow history. Uploading anonymised counts to Damira is off unless you set `DAMIRA_TELEMETRY=1`; no config text, file names or hostnames are ever sent.

## What's in the box

| Skill | What it does |
|---|---|
| `troubleshoot` | Structured diagnosis with ranked root causes and vendor-specific CLI, plus incident report and runbook templates |
| `upgrade-plan` | Upgrade assessment from real release notes and CVE data, plus MOP and change-control templates |
| `config-audit` | Local config security audit; findings grouped by severity with the fix |
| `generate-config` | Device configuration for Cisco, Juniper, Arista, Palo Alto and Fortinet |
| `generate-playbook` | Ansible playbooks for repeatable changes across a fleet |
| `generate-automation` | Python automation (Nornir, Netmiko or Scrapli) with a YAML inventory, checked locally before it's handed back |
| `generate-terraform` | Terraform for NetBox, PAN-OS, FortiOS, Meraki, IOS-XE and NX-OS, validated locally and ending with `terraform plan` |
| `generate-tests` | pyATS/Genie before-and-after checks that prove a change did what it should, plus pytest tests for your scripts |
| `generate-pipeline` | GitHub Actions or GitLab CI for network changes: lint, check mode or plan, a manual approval gate, then deploy |
| `generate-workbook` | Excel workbooks (.xlsx) for migrations, audits and change control, with every command checked against the saved evidence |
| `generate-diagram` | Topology diagrams from your configs and CDP/LLDP output: SVG, HTML preview, Mermaid and D2, optional PowerPoint slide |
| `source-of-truth-change` | NetBox/Nautobot intent to a validated change, handed to an AAP check-mode job, a pyATS diff or a Terraform plan |
| `generate-lab` | ContainerLab topologies to rehearse a change before the maintenance window |
| `lab-test-change` | Deploy a throwaway ContainerLab lab, apply the change, run checks, report pass/fail, always destroy the lab (needs Docker + containerlab) |

## Your AI never touches your devices

In advisor mode a hook stops the agent reaching network gear on its own. Damira's own
device tools are blocked outright. A shell `ssh`, `telnet` or `nc` is handed to you to
approve, because not every host is network gear — set **device_gate** to `strict` to block
those too. If the hook can't evaluate a call, it blocks it. A second hook stops the agent from writing a MOP or runbook into
`documents/` when no Damira lookup in the session backs it up.

Config audits run on your machine, so your configs never leave it.

## Supported platforms

Cisco (IOS/IOS-XE/NX-OS, and CUCM for voice), Juniper Junos, Arista EOS, Palo Alto
PAN-OS, Fortinet FortiOS.

## Support

Bugs and feature requests: [Issues](https://github.com/ciscoittech/damira-plugins/issues).
Please strip configs, hostnames and customer details from anything you post.
