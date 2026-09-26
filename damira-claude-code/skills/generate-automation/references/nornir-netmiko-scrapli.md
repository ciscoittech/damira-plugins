# Nornir, Netmiko and Scrapli

Reference pack 1.0 (2026-09-24), condensed from Damira's server skill `network-automation`.

## Which one

| Need | Use |
|---|---|
| A fleet, inventory-driven, parallel | Nornir 3 + `nornir_netmiko` (or `nornir_scrapli`) |
| One-off script against a few devices | Netmiko `ConnectHandler` |
| Fast, async, or strict prompt handling | Scrapli (`scrapli`, `scrapli[asyncssh]`) |
| Config replace/merge with diff + rollback | NAPALM (`load_merge_candidate` → `compare_config`) |

## Nornir inventory (SimpleInventory)

```
automation/inventory/hosts.yaml     # per-device: hostname, platform, groups
automation/inventory/groups.yaml    # per-group: platform, connection_options
automation/inventory/defaults.yaml  # shared; NO credentials here
```

```yaml
# hosts.yaml
rtr1:
  hostname: 192.0.2.1
  groups: [ios]
# groups.yaml
ios:
  platform: cisco_ios        # Netmiko device_type; Scrapli uses cisco_iosxe
```

Credentials come from the environment at runtime, never from the YAML:

```python
import os
from nornir import InitNornir

nr = InitNornir(
    runner={"plugin": "threaded", "options": {"num_workers": 20}},
    inventory={"plugin": "SimpleInventory", "options": {
        "host_file": "automation/inventory/hosts.yaml",
        "group_file": "automation/inventory/groups.yaml",
        "defaults_file": "automation/inventory/defaults.yaml"}},
)
nr.inventory.defaults.username = os.environ["NET_USERNAME"]
nr.inventory.defaults.password = os.environ["NET_PASSWORD"]
```

Tasks: `nornir_netmiko.tasks.netmiko_send_command` (`use_textfsm=True`),
`netmiko_send_config`, `netmiko_save_config`; `nornir_scrapli.tasks.send_command`,
`send_configs`. Filter with `nr.filter(platform="cisco_ios")` or `F(groups__contains="core")`.
Check `result.failed` / `result.failed_hosts` — Nornir does not raise on per-host failure.

## Platform strings

| Platform | Netmiko `device_type` | Scrapli platform | NAPALM driver |
|---|---|---|---|
| IOS / IOS-XE | `cisco_ios` / `cisco_xe` | `cisco_iosxe` | `ios` |
| NX-OS | `cisco_nxos` | `cisco_nxos` | `nxos_ssh` |
| IOS-XR | `cisco_xr` | `cisco_iosxr` | `iosxr` |
| Arista EOS | `arista_eos` | `arista_eos` | `eos` |
| Junos | `juniper_junos` | `juniper_junos` | `junos` |
| PAN-OS | `paloalto_panos` | — (community) | — |
| FortiOS | `fortinet` | — (community) | — |

## Netmiko essentials

```python
import os
from netmiko import ConnectHandler

device = {"device_type": "cisco_ios", "host": host,
          "username": os.environ["NET_USERNAME"], "password": os.environ["NET_PASSWORD"],
          "timeout": 60}
with ConnectHandler(**device) as conn:
    parsed = conn.send_command("show ip interface brief", use_textfsm=True)
    conn.send_config_set(lines)       # enters/exits config mode itself
    conn.save_config()
```

- `read_timeout=` on `send_command` for slow output (`show tech`).
- Junos: `send_config_set(..., exit_config_mode=False)` then `conn.commit(confirm=True, confirm_delay=5)`.
  That is `commit confirmed 5`: verify reachability, then send a second plain `conn.commit()`
  within 5 minutes, or Junos rolls the change back on its own.

## Safety rules

- `--dry-run` prints the commands (or the NAPALM diff) instead of sending them.
- Back up the running config before any push; keep it next to the run log.
- Context managers / `try/finally` for every connection.
- Parse with TextFSM/Genie (`use_textfsm=True`, `use_genie=True`), not regex on raw text.
- Pin versions in `requirements.txt` (`nornir==3.*`, `nornir-netmiko`, `netmiko`, `ntc-templates`).
