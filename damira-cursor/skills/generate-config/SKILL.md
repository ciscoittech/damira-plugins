---
name: generate-config
description: Write a deployable configuration for a real network device. Use when the user asks for the config, CLI, or commands to set up a feature on a specific platform — BGP peering, OSPF, VLANs and trunks, ACLs, NAT, VPN, QoS, AAA/TACACS, SNMPv3, NTP — on Cisco IOS/IOS-XE/NX-OS, Arista EOS, Juniper Junos, Palo Alto, or Fortinet. Also fires on "give me the commands for..." and "how do I set up X on a 9300". Not for lab topologies (use generate-lab), not for fleet-wide automation (use generate-playbook), and not for reviewing a config that already exists (use config-audit).
---

# Network Config Generation

Generate production-ready device configuration files.

## Step 1: Gather requirements

- **Device** — Cisco ISR4451, Arista 7050X, Palo Alto PA-3260, Juniper MX204, …
- **Platform / OS version** — IOS-XE 17.9, EOS 4.28, PAN-OS 11.1
- **Features** — BGP, OSPF, VLANs, ACLs, NAT, NTP, AAA, SNMP
- **Interfaces** — addresses, descriptions, link types
- **Hostname** — used for the filename

## Step 2: Verify syntax

For any feature where you are not fully certain of the syntax on that platform and
version:

```bash
~/.damira/bin/damira search-vendor-docs \
  "<feature> configuration <platform> <version>" --vendor "<vendor>"
```

Pay particular attention to:
- version-specific differences (IOS vs IOS-XE vs NX-OS)
- feature availability on the specific hardware
- defaults that changed between versions

**If the lookup exits non-zero, say so.** Do not emit syntax you could not verify without
labelling it. The engineer is going to paste this into a device.

## Step 3: Write the config

- `hostname`, management, AAA, NTP, logging, SNMP baseline
- all requested features, correct syntax
- comments (`!` for Cisco, `#` for Juniper/Arista) explaining each section
- vendor best practice — `enable secret` not `enable password`, SNMPv3 not v2c

## Step 4: Save

`configs/{hostname}.cfg` — e.g. `configs/chi-rtr-01.cfg`, `configs/fw-dmz-01.conf`

## Step 5: Summarise

- what was configured
- **every assumption you made** — call these out explicitly, they are where deployments break
- recommended pre-deployment checks

Offer to run `config-audit` over what you just wrote. Catching a missing `service
password-encryption` before deployment is cheaper than after.
