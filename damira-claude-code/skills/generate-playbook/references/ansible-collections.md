# Ansible collections for network devices

Reference pack 1.0 (2026-09-24), condensed from Damira's server skills `ansible-advanced` and
`network-automation`. Module parameters move between collection versions — confirm anything
you are unsure of with `damira_search_vendor_docs` / `damira search-vendor-docs`.

## Collection, network_os and connection per platform

| Platform | Collection | `ansible_network_os` | `ansible_connection` |
|---|---|---|---|
| Cisco IOS / IOS-XE | `cisco.ios` | `cisco.ios.ios` | `ansible.netcommon.network_cli` |
| Cisco IOS-XR | `cisco.iosxr` | `cisco.iosxr.iosxr` | `network_cli` or `netconf` |
| Cisco NX-OS | `cisco.nxos` | `cisco.nxos.nxos` | `network_cli` or `httpapi` (NX-API) |
| Arista EOS | `arista.eos` | `arista.eos.eos` | `network_cli` or `httpapi` (eAPI) |
| Juniper Junos | `juniper.device` (2.x) | `juniper.device.junos` | `netconf` (preferred) or `network_cli` |
| Palo Alto PAN-OS | `paloaltonetworks.panos` | n/a — `provider:` dict per task | `local` |
| Fortinet FortiOS | `fortinet.fortios` | `fortinet.fortios.fortios` | `httpapi` |
| F5 BIG-IP | `f5networks.f5_modules` | n/a — `provider:` dict | `local` |

Junos: `junipernetworks.junos` (11.x) is now a deprecation shell whose modules redirect to
`juniper.device` (redirects removed after 2028-04-01); ansible-lint's production profile
fails `fqcn[canonical]` on the old names. Write `juniper.device.junos_config`,
`juniper.device.junos_banner`, etc.

Install: `ansible-galaxy collection install cisco.ios arista.eos ...` — pin versions in
`collections/requirements.yml` for anything that runs in CI.

## Resource modules vs `*_config`

- Prefer resource modules — `ios_vlans`, `ios_interfaces`, `ios_l3_interfaces`,
  `ios_bgp_global`, `ios_ntp_global`, `ios_logging_global`, `ios_snmp_server`, `eos_vlans`,
  `nxos_vlans`, `junos_vlans`. They are idempotent and support `state:` `merged` (additive),
  `replaced` (per-resource), `overridden` (whole resource set — dangerous), `deleted`,
  `gathered` (read), `rendered` (offline render, no device).
- `*_config` with `lines:`/`parents:` is for config with no resource module. It is only
  idempotent if the lines match the running config exactly (spacing, abbreviations).
  Secret-bearing lines never match: IOS shows `key 0 <x>` back as `key 7`/`key 6`, and
  `snmp-server user` is not in the running config at all — those tasks report `changed`
  on every run and `--check --diff` always shows them.
- Save with `*_config: save_when: modified`, not a raw `write memory` command.
- PAN-OS: object/rule modules (`panos_address_object`, `panos_security_rule`), then an
  explicit `panos_commit_firewall` / `panos_commit_panorama` task.
- FortiOS: one module per CLI table (`fortios_firewall_policy`, `fortios_system_ntp`),
  `vdom:` on every task, `state: present`.

## Check mode (`--check --diff`)

- Resource modules and `*_config` support check mode on IOS/NX-OS/EOS/Junos.
- `*_command` modules in check mode run `show` commands only and skip anything else with a
  warning — don't rely on them for state changes; guard such tasks with
  `when: not ansible_check_mode`.
- Junos `junos_config` in check mode loads the candidate, reports the diff and discards it;
  set `check_commit: true` to have the device run `commit check` as well.
- PAN-OS commit tasks must be skipped in check mode.

## Structure and conventions

- `gather_facts: false` for network plays (no Python on the device).
- Fully-qualified module names (`cisco.ios.ios_vlans`, not `ios_vlans`) — ansible-lint's
  production profile fails without them.
- Every task has a `name:`; handlers for save/commit; `block`/`rescue` with rollback around
  state changes; `serial:` to limit blast radius on big fleets.
- Credentials: Ansible Vault (`ansible-vault encrypt_string`) or `lookup('env', 'NET_PASSWORD')`;
  never a literal `ansible_password` in inventory.
- `ansible_command_timeout: 60` for slow platforms; `ansible_become: true` +
  `ansible_become_method: enable` on IOS when the login lands in user EXEC.
- Variable precedence trap: `-e` extra vars override everything, including role vars.

## Inventory skeleton

```yaml
all:
  children:
    ios:
      hosts:
        rtr1: {ansible_host: 192.0.2.1}
      vars:
        ansible_network_os: cisco.ios.ios
        ansible_connection: ansible.netcommon.network_cli
        ansible_user: "{{ lookup('env', 'NET_USERNAME') }}"
        ansible_password: "{{ lookup('env', 'NET_PASSWORD') }}"
    eos:
      hosts:
        sw1: {ansible_host: 192.0.2.2}
      vars:
        ansible_network_os: arista.eos.eos
        ansible_connection: ansible.netcommon.httpapi
        ansible_httpapi_use_ssl: true
```
