# Damira — Give Your AI the CCIE Playbook

**CCIE-level network operations inside Cursor.** Troubleshooting, upgrade planning,
config audit, and device configuration — grounded in live vendor documentation, release
notes, and CVE data instead of the model's memory.

Your AI writes the MOP. Damira makes sure it's true.

## Try it in 60 seconds — no signup

**Cursor:**

```bash
agent plugin marketplace add https://github.com/ciscoittech/damira-plugins
```

Then `/plugins` in the Cursor agent, or **Settings → Plugins** in the IDE, and install
**damira**.

**Claude Code:**

```
/plugin marketplace add ciscoittech/damira-plugins
/plugin install damira@damira-plugins
```

Either way a shared demo key (50 queries/day) is built in, so it works immediately.
Claude Code asks for your key, execution mode and shell device gate when you enable the
plugin; leave the key blank for the demo key. Answers on the demo key say so. To add or
change a key later, see [API key](https://damiraai.com/docs/install#api-key). The first time each Damira tool runs, Claude Code asks for
permission — choose always-allow and it won't ask again.

Ask it something real:

> my OSPF adjacency is stuck in EXSTART between a 4451 and a Nexus 9k

You'll get a structured diagnosis — most-probable causes ranked, the exact vendor-specific
commands to run, and verification steps that prove the fix. Not "check the config."

## Your AI never touches your devices

**Advisor mode is the default and a device gate enforces it.** The plugin ships a hook
that blocks the agent from SSHing to network gear — including when the agent is run with
every safety flag disabled. Damira recommends the exact commands; the engineer runs them
and pastes the output back.

Three more things engineers rightfully ask about:

- **Config audits run locally.** `config-audit` is a bundled script — your configs never
  leave your machine.
- **Refusals are never answers.** If the backend returns anything that isn't a real
  answer — an error, a refusal, an empty response — the tools exit non-zero and the agent
  is told not to use it as source material. No confident documents built on failures.
- **No hidden toolchain.** No PyPI, no pip, no uvx. Standard-library Python scripts only.

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
| `troubleshoot` | Structured diagnosis with ranked root causes and vendor-specific CLI — plus incident report and runbook templates |
| `upgrade-plan` | Upgrade assessment from real release notes and CVE data — plus MOP and change control templates |
| `config-audit` | Local config security audit; findings grouped by severity with remediation |
| `generate-config` | Device configuration for Cisco, Juniper, Arista, Palo Alto, and Fortinet |
| `generate-playbook` | Ansible playbooks for network automation |
| `generate-lab` | ContainerLab topologies to rehearse a change before the maintenance window |
| `generate-automation` | Python automation (Nornir, Netmiko or Scrapli) with a YAML inventory, checked locally before it's handed back |
| `generate-terraform` | Terraform for NetBox, PAN-OS, FortiOS, Meraki, IOS-XE and NX-OS, validated locally and ending with `terraform plan` |
| `generate-tests` | pyATS/Genie before-and-after checks that prove a change did what it should, plus pytest tests for your scripts |
| `generate-pipeline` | GitHub Actions or GitLab CI for network changes: lint, check mode or plan, a manual approval gate, then deploy |
| `generate-workbook` | Excel workbooks (.xlsx) for migrations, audits and change control, with every command checked against the saved evidence |
| `generate-diagram` | Topology diagrams from your configs and CDP/LLDP output: SVG, HTML preview, Mermaid and D2, optional PowerPoint slide |
| `source-of-truth-change` | NetBox/Nautobot intent to a validated change, handed to an AAP check-mode job, a pyATS diff or a Terraform plan |

**How the division of labor works:** Damira supplies the domain data — vendor docs, CVE
lookups, version-specific caveats, structured diagnoses. Your AI assembles that into the
deliverables your change process actually requires: MOPs, change controls, runbooks,
incident reports. The templates for those documents are bundled, built on CCIE and ITIL
practice.

## Using your own key

The demo key is for kicking the tires. For real use:

```bash
export DAMIRA_API_KEY='oncall_sk_...'      # add to ~/.zshrc or ~/.bashrc
```

Get a key at [damiraai.com](https://damiraai.com/dashboard/api-keys). One export line —
the [plugin README](damira-cursor/README.md) explains exactly why it's an export and not
a settings field, along with setup for the optional MCP server (`damira install-mcp`),
which brings the same tools to Claude Desktop, Claude Code, and Windsurf.

## Supported platforms

Cisco (IOS/NX-OS and CUCM for voice), Juniper Junos, Arista EOS, Palo Alto PAN-OS,
Fortinet FortiOS.

## Support

- Bugs and feature requests: [Issues](https://github.com/ciscoittech/damira-plugins/issues)
- Product and pricing: [damiraai.com](https://damiraai.com)

## License

MIT
