---
name: generate-config
description: Write a deployable configuration for a real network device. Use when the user asks for the config, CLI, or commands to set up a feature on a specific platform — BGP peering, OSPF, VLANs and trunks, ACLs, NAT, VPN, QoS, AAA/TACACS, SNMPv3, NTP — on Cisco IOS/IOS-XE/NX-OS, Arista EOS, Juniper Junos, Palo Alto, or Fortinet. Also fires on "give me the commands for..." and "how do I set up X on a 9300". Not for lab topologies (use generate-lab), not for fleet-wide automation (use generate-playbook), and not for reviewing a config that already exists (use config-audit).
allowed-tools: mcp__plugin_damira_damira__damira_search_vendor_docs, mcp__damira__damira_search_vendor_docs
---

# Network Config Generation

Generate production-ready device configuration files.

## Workflow

### Step 1: Gather Requirements

Ask the user for:
- **Device type** — e.g., Cisco ISR4451, Arista 7050X, Palo Alto PA-3260, Juniper MX204
- **Platform/OS version** — e.g., IOS-XE 17.9, EOS 4.28, PAN-OS 11.1
- **Features** — e.g., BGP peering, OSPF, VLANs, ACLs, NAT, NTP, AAA, SNMP
- **Interfaces** — IP addresses, descriptions, link types
- **Hostname** — for the config filename

### Step 2: Verify Syntax

Call `damira_search_vendor_docs` to verify platform-specific CLI syntax for any feature you're not 100% certain about. Pay attention to:
- Version-specific syntax differences (IOS vs IOS-XE vs NX-OS)
- Feature availability on the specific hardware platform
- Default behaviors that differ between versions

### Step 3: Generate Config

Write a complete, deployable configuration:
- Include `hostname`, management, AAA, NTP, logging, SNMP baseline
- Include all requested features with correct syntax
- Add comments (`!` for Cisco, `#` for Juniper/Arista) explaining each section
- Follow vendor best practices (use `enable secret` not `enable password`, use SNMPv3, etc.)

### Step 4: Save to Workspace

Save the config file to `configs/{hostname}.cfg`

Example filenames:
- `configs/chi-rtr-01.cfg`
- `configs/nyc-sw-core-01.cfg`
- `configs/fw-dmz-01.conf`

### Step 5: Validate

**Delegate this loop to the `damira:damira-fixer` agent** (it runs on Haiku). Give it the path, `--skill generate-config`, and `<plugin root>`. It runs the command below, fixes only what the findings name, and stops after 3 rounds. Read its report: a change to a device command, module or resource is your call, not its. If the agent isn't available, run the loop yourself as below.

After writing the files, run the validator. It ships in this plugin, two levels above
this skill's base directory: `<plugin root>/scripts/damira.py`.

```bash
python3 "<plugin root>/scripts/damira.py" validate configs/{hostname}.cfg
```

It lints and syntax-checks locally (no API call) and exits non-zero on any failure. Fix every
FAIL and re-run until it passes, at most 3 rounds; if it still fails, tell the user what is
left. A `skipped` check means the tool isn't installed — pass the install hint on, don't
treat it as a pass. (Saving under `configs/`, `automation/` or `playbooks/` also runs it
automatically.)

### Step 6: Summarise and hand back

After saving, briefly summarize:
- What was configured
- Any assumptions made
- Recommended pre-deployment checks
