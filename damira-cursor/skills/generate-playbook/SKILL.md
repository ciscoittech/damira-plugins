---
name: generate-playbook
description: Write an Ansible playbook, inventory, and group_vars for a repeatable change across many network devices, then validate it locally before handing it back. Use when the user asks for Ansible by name, or asks how to push the same change to a fleet — VLANs, banners, NTP/AAA, SNMPv3, config backup, compliance checks — using cisco.ios, cisco.nxos, arista.eos, juniper.device (Junos), paloaltonetworks.panos, or fortinet.fortios. For Python (Nornir/Netmiko/Scrapli) use generate-automation, for Terraform use generate-terraform, for pyATS/pytest checks use generate-tests, for a CI pipeline use generate-pipeline, and for a single device's config use generate-config.
---

# Ansible playbook generation

You write the playbook. Damira supplies the vendor facts and the gate: every playbook goes
through `damira validate` before you hand it back.

## Step 1: Gather requirements

- **Task** — deploy VLANs, back up configs, push NTP/AAA/SNMPv3, compliance check
- **Targets** — how many devices, what platform and OS version
- **Variables** — VLAN IDs, interface names, server IPs
- **Connection** — `network_cli` (SSH), `httpapi` (eAPI/NX-API), or `netconf`

If the user named a different framework, use the sibling skill instead (see the description).

## Step 2: Look up the modules

Run `~/.damira/bin/damira search-vendor-docs "<query>" --vendor <vendor>` for the collection and module you plan to use, e.g.
`"ansible cisco.ios ios_ntp_global parameters"` with the vendor set. Module names and
parameters change between collection versions; this lookup is what keeps the playbook
from using a parameter that no longer exists. **If the lookup fails, say so** rather than
emitting parameters you could not verify.

Read `references/ansible-collections.md` (beside this file) for the collection per platform,
resource modules vs `*_config`, connection plugins, and check-mode caveats.

If the change is a standard baseline (NTP, AAA/TACACS+, SNMPv3, syslog) on IOS,
NX-OS, EOS or Junos, the plugin ships golden templates. Render the device lines with
`--secrets ansible`, so secret values (TACACS key, SNMP passphrases) come out as
`{{ lookup('env', 'NAME') }}` and are resolved when the playbook runs — never render real
secrets into your context or into a playbook:
`~/.damira/bin/damira render <task> --platform <p> --vars vars.yml --secrets ansible`
and push them with the platform's `*_config` module (Junos: `juniper.device.junos_config`
with the `set` lines under `lines:` — it takes set/delete lines directly and has no `format`
option; drop the `#` comment lines, which it rejects), instead of hand-writing the lines. Banners are the exception: use the
banner modules (`cisco.ios.ios_banner`, `cisco.nxos.nxos_banner`, `arista.eos.eos_banner`,
`juniper.device.junos_banner`) with the text as a variable — a
delimited `banner login ^ ... ^` block does not fit `*_config` `lines:`.

## Step 3: Write the playbook

- **Inventory** — YAML, device groups, `ansible_network_os` + `ansible_connection` per group
- **Credentials** — Ansible Vault or env lookups (`lookup('env', 'NET_PASSWORD')`), never inline
- **Tasks** — resource modules (`state: merged`) where one exists; `*_config` only for lines
  with no resource module. `gather_facts: false`. Fully-qualified module names.
- **Error handling** — `block`/`rescue` around anything that changes device state
- **Idempotency** — safe to run repeatedly. Resource modules are; `*_config` `lines:` only
  when they match the running config exactly. Golden AAA/SNMPv3 lines carrying secrets
  never do (IOS shows `key 7`, hides `snmp-server user`), so they report `changed` every run.
  Say so in the hand-back, or split them into a task with `when:` on a first-run/rotation flag

Save under `playbooks/`: `playbooks/{task}.yml`, `playbooks/inventory/{group}.yml`,
`playbooks/group_vars/{group}.yml`.

## Validate loop

**Delegate this loop to the `damira-fixer` subagent** (pinned to a cheap model). Give it the path and `--skill generate-playbook`. It runs the command below, fixes only what the findings name, and stops after 3 rounds. Read its report: a change to a device command, module or resource is your call, not its. If the subagent isn't available, run the loop yourself as below.

The validator is `~/.damira/bin/damira validate`. It runs locally (yamllint, `ansible-playbook
--syntax-check`, `ansible-lint --profile production`) and makes no API call. `--skill` tags
the local workflow event with this skill.

```bash
~/.damira/bin/damira validate playbooks/ --skill generate-playbook --host cursor
```

1. Run it on everything you wrote.
2. Fix every FAIL and re-run — at most 3 rounds.
3. Still failing after 3 rounds: stop, tell the user which checks fail and why. Do not hand
   it back as finished.
4. A `skipped` check means the tool is not installed — pass the install hint on; it is not
   a pass. An `UNVERIFIED` result is not a pass either.
5. `couldn't resolve module/action '<ns>.<coll>.<module>'` or
   `syntax-check[unknown-module]` means the collection is not installed, not that the module
   is wrong. Do not rename or swap modules to make it go away: treat it like a skipped check,
   tell the user to run `ansible-galaxy collection install <ns>.<coll>` (or `-r
   collections/requirements.yml`) and re-validate, and don't count it against the 3 rounds.

## Step 4: Hand back

Lead with the dry run, then a single-device first run:

```bash
ansible-playbook -i playbooks/inventory/{group}.yml playbooks/{task}.yml --check --diff
# review the diff, then one device first:
ansible-playbook -i playbooks/inventory/{group}.yml playbooks/{task}.yml --limit <one-host>
```

State what validate reported (pass / warnings / skipped tools) and any assumption you made.
