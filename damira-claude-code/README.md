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

When you enable the plugin, Claude Code asks for two settings:

- **API key**: from [damiraai.com → Dashboard → API Keys](https://damiraai.com/dashboard/api-keys).
  It's stored in your system keychain, not in a settings file. Leave it blank to try Damira
  on the shared demo key (50 queries a day).
- **Execution mode**: leave on `advisor`. Damira recommends the exact commands and you
  run them. `guided` and `lab` let the agent run read-only `show` commands itself and are
  meant for lab gear only.

Needs Python 3 (`python3 --version`). No pip, no uvx: everything runs on the standard
library.

## What's in the box

| Skill | What it does |
|---|---|
| `troubleshoot` | Structured diagnosis with ranked root causes and vendor-specific CLI, plus incident report and runbook templates |
| `upgrade-plan` | Upgrade assessment from real release notes and CVE data, plus MOP and change-control templates |
| `config-audit` | Local config security audit; findings grouped by severity with the fix |
| `generate-config` | Device configuration for Cisco, Juniper, Arista, Palo Alto and Fortinet |
| `generate-playbook` | Ansible playbooks for repeatable changes across a fleet |

## Your AI never touches your devices

In advisor mode a hook blocks the agent from reaching network gear: `ssh`, `telnet` and
`nc` through the shell, and Damira's own device tools. If the hook can't evaluate a call,
it blocks it. A second hook stops the agent from writing a MOP or runbook into
`documents/` when no Damira lookup in the session backs it up.

Config audits run on your machine, so your configs never leave it.

## Supported platforms

Cisco (IOS/IOS-XE/NX-OS, and CUCM for voice), Juniper Junos, Arista EOS, Palo Alto
PAN-OS, Fortinet FortiOS.

## Support

Bugs and feature requests: [Issues](https://github.com/ciscoittech/damira-plugins/issues).
Please strip configs, hostnames and customer details from anything you post.
