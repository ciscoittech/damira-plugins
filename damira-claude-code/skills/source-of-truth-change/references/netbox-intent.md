# Reading intent from NetBox or Nautobot

The source of truth says what the network *should* be. It is not live state: a device can
drift from it, which is what the pyATS hand-off measures. Read it, don't write it. If the
intent is wrong, the engineer fixes it in NetBox or Nautobot and you read it again.

## Scope the query

Filter every query. Pulling all devices wastes context and invites changes nobody asked for.

| Filter | NetBox 4.x | Nautobot 2.x |
|---|---|---|
| Where | `site`, `location`, `region` | `location` (sites became locations) |
| What kind | `role` (was `device_role` before 3.6) | `role` |
| Lifecycle | `status=active` | `status=Active` |
| Ad-hoc groups | `tag` | `tags` |

Start with devices, then fetch only the related objects the change touches.

## Objects that make up a change

| Need | Object | Fields to keep |
|---|---|---|
| Targets | device | name, platform, role, site/location, primary IP, status |
| Access/trunk ports | interface | name, enabled, mode, untagged VLAN, tagged VLANs, description |
| Layer 2 | VLAN | VID, name, VLAN group or site |
| Addressing | prefix, IP address | prefix, VRF, assigned interface, role |
| Per-device settings | config context | the rendered context (NetBox: ask for it on the device) |

Keep the object IDs. They go in the report and in the change request, so a reviewer can
see exactly which records drove the change.

## Platform to automation

Map the device platform to the framework's connection value; don't guess from the name.

| Typical platform slug | `ansible_network_os` | Terraform provider |
|---|---|---|
| cisco_ios / ios-xe | `cisco.ios.ios` | CiscoDevNet/iosxe |
| cisco_nxos | `cisco.nxos.nxos` | CiscoDevNet/nxos |
| arista_eos | `arista.eos.eos` | none: use Ansible |
| juniper_junos | `junipernetworks.junos.junos` | none in common use |
| panos | `paloaltonetworks.panos` modules | PaloAltoNetworks/panos |

Nautobot 2.x platforms carry a `network_driver` whose mappings include the Ansible value;
prefer it when present. Slugs are set per site, so if a platform slug is not in this table,
ask the engineer rather than picking the nearest match.

## Inventory

- If AAP syncs its inventory from NetBox (the `netbox.netbox.nb_inventory` source), use
  that inventory and target hosts with a limit. Don't write a second, static inventory.
- For plain Ansible, generate the inventory from the queried devices: host name, primary
  IP as `ansible_host`, the mapped `ansible_network_os`, grouped by role or site.

## Contradictions to stop on

- An interface's VLAN that doesn't exist at the device's site or VLAN group.
- A device in scope with no platform or no primary IP.
- A prefix assigned to an interface on a device outside the filter.
- Status planned or decommissioning on a device the change targets.

Report the records and IDs. Don't resolve the conflict yourself.

## Secrets

Credentials never come from the source of truth into generated files, even if a custom
field or secrets plugin holds them. Use environment or vault lookups, the same as the
generator skills do.
