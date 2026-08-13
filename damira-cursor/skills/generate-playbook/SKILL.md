---
name: generate-playbook
description: Write an Ansible playbook, inventory, and group_vars for a repeatable change across many network devices. Use when the user asks for Ansible by name, or asks how to push the same change to a fleet — VLANs, banners, NTP/AAA, config backup, compliance checks — using cisco.ios, cisco.nxos, arista.eos, junipernetworks.junos, paloaltonetworks.panos, or fortinet.fortios. Do not use if the user wants Python/Netmiko, Nornir, pyATS, or Terraform, and not for configuring a single device (use generate-config).
---

# Ansible Playbook Generation

Generate production-ready Ansible playbooks for network automation.

## Step 1: Gather requirements

- **Task** — deploy VLANs, back up configs, push NTP/AAA, compliance check
- **Targets** — how many devices, what type
- **Platform** — determines the collection
- **Variables** — VLAN IDs, interface names, IP ranges

## Step 2: Verify module syntax

```bash
~/.damira/bin/damira search-vendor-docs \
  "ansible <collection> <module> <task>" --vendor "<vendor>"
```

Verify the collection and module names, parameters, and any version-specific behaviour.
Module names and parameters change between collection versions more often than people
expect — this is worth the lookup.

Collections:

| Platform | Collection |
|---|---|
| Cisco IOS / IOS-XE | `cisco.ios` |
| Cisco NX-OS | `cisco.nxos` |
| Arista EOS | `arista.eos` |
| Juniper Junos | `junipernetworks.junos` |
| Palo Alto | `paloaltonetworks.panos` |
| Fortinet | `fortinet.fortios` |

**If the lookup fails, say so** rather than emitting module parameters you could not
verify.

## Step 3: Write the playbook

- **Inventory** — hosts file with device groups
- **Group vars** — `ansible_network_os`, `ansible_connection`, per-platform settings
- **Playbook** — tasks with correct module usage, handlers, tags
- **Error handling** — `block`/`rescue` around anything that changes device state
- **Idempotency** — safe to run repeatedly; this is not optional for network automation

## Step 4: Save

- Playbook: `playbooks/{task-name}.yml`
- Inventory: `playbooks/inventory/{group-name}.yml`
- Group vars: `playbooks/group_vars/{group}.yml`

## Step 5: Run instructions

Always lead with the dry run:

```bash
ansible-playbook -i playbooks/inventory/hosts.yml playbooks/{task-name}.yml --check --diff
# review the diff, then:
ansible-playbook -i playbooks/inventory/hosts.yml playbooks/{task-name}.yml
```

Recommend `--limit` to a single device for the first real run. A playbook that is wrong
against one device is a bad afternoon; the same playbook against the fleet is an outage.
