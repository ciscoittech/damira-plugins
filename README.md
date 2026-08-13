# Damira Plugins

CCIE-level network operations for AI coding agents. Damira supplies the domain data —
live vendor docs, CVE lookups, release notes, structured GIDRP troubleshooting, upgrade
assessments — and your agent writes the deliverables: MOPs, change controls, runbooks,
incident reports.

**Advisor-mode by default.** A device gate hook blocks the agent from SSHing to network
devices, even under `--force`. Damira recommends exact commands; the engineer runs them.

## Install (Cursor)

Add this repo as a plugin marketplace, then install:

```bash
agent plugin marketplace add https://github.com/ciscoittech/damira-plugins
agent plugin install damira
```

Or in the IDE: Settings → Plugins → Add Marketplace → paste the repo URL.

### API key

The plugin works out of the box on a shared demo key (50 queries/day). For your own key:

```bash
export DAMIRA_API_KEY='oncall_sk_...'      # add to ~/.zshrc or ~/.bashrc
```

Get one at [damiraai.com/dashboard/api-keys](https://damiraai.com/dashboard/api-keys).
Full setup detail, including the optional MCP server for Claude Desktop / Claude Code /
Windsurf (`damira install-mcp` — no PyPI, no pip, standard library only), is in
[`damira-cursor/README.md`](damira-cursor/README.md).

## What's in the box

| Skill | What it does |
|---|---|
| `troubleshoot` | GIDRP diagnosis with vendor-specific CLI, incident report + runbook templates |
| `upgrade-plan` | Upgrade assessment from real release notes and CVE data, MOP + change control templates |
| `config-audit` | Local config security audit — config text never leaves your machine |
| `generate-config` | Device configuration for Cisco, Juniper, Arista, Palo Alto, Fortinet |
| `generate-playbook` | Ansible playbooks for network automation |
| `generate-lab` | ContainerLab topologies to rehearse changes |

Plus the same capabilities as 7 MCP tools for clients without skill support.

## Support

Issues and feature requests: [github.com/ciscoittech/damira-plugins/issues](https://github.com/ciscoittech/damira-plugins/issues)
Product: [damiraai.com](https://damiraai.com)

## License

MIT
