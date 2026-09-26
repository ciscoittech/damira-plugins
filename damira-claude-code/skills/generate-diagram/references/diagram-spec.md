# DiagramSpec (`topology.json`)

The spec is the contract between whoever finds the topology and the renderer. `damira
diagram build` writes it from `configs/`. You can also write or edit it by hand, for
example from a source of truth (NetBox) or from what the engineer tells you. The renderer
validates it and fills defaults, so only `nodes[].id` and `links[].a`/`b` are required.

```json
{
  "version": 1,
  "title": "Chicago core",
  "layout": "auto",
  "nodes": [
    {"id": "core1", "label": "core1", "role": "router", "platform": "ISR4451-X/K9",
     "mgmt_ip": "10.1.1.1", "tier": 0, "zone": "", "external": false}
  ],
  "links": [
    {"a": "core1", "a_if": "Gi0/1", "b": "core2", "b_if": "Gi0/1", "subnet": "10.0.0.0/30",
     "kind": "l3", "source": "cdp", "protocols": ["bgp", "ospf"]}
  ],
  "zones": [],
  "warnings": []
}
```

## Nodes

| Field | Values | Notes |
|---|---|---|
| `id` | unique string | Hostname without the domain. Links refer to it. |
| `label` | string | What the diagram shows. Defaults to `id`. |
| `role` | router, switch, firewall, wlc, ap, server, host, cloud | Sets the shape and colour. Unknown values become `router`. |
| `platform` | string | Model or OS, shown under the label. |
| `mgmt_ip` | string | Loopback, else SVI/Mgmt, else the CDP/LLDP address. |
| `tier` | integer, 0 = top | Row in the tiered layout. Lower is closer to the edge. |
| `zone` | string | Nodes with the same zone are grouped (Mermaid subgraph, D2 container). |
| `external` | bool | No config for it: an ISP, an AP, a peer. Drawn dashed. |

## Links

| Field | Values | Notes |
|---|---|---|
| `a`, `b` | node ids | Order doesn't matter. |
| `a_if`, `b_if` | short names (`Gi0/1`) | Empty when unknown, such as the far end of an eBGP peer. |
| `subnet` | CIDR | Shown mid-link. |
| `kind` | l2, l3, bgp, ospf | l2/l3 are solid; bgp/ospf mean "session with no known link" and are dashed. |
| `source` | cdp, lldp, subnet, bgp, ospf, manual | How the link was found. Use `manual` for links you add. |
| `protocols` | list | Protocols riding the link, such as `["bgp", "ospf"]`. |

## How `build` decides

1. CDP/LLDP give physical links with both interfaces. These are the most trustworthy.
2. A /29 to /31 subnet configured on exactly two devices is an L3 link. When CDP saw the
   same link, the two merge and the link takes the subnet.
3. A BGP neighbour rides an existing link, else a connected subnet, else becomes a dashed
   `bgp` edge. An unknown peer becomes an external `cloud` node named `ext-AS<asn>`.
4. Role comes from the CDP/LLDP platform, then capabilities, then the hostname, then the
   config (switchport only means switch). Tier follows role: cloud, firewall, router/core,
   distribution/WLC, switch, everything else.
5. `layout: auto` picks leaf-spine when there are nodes named spine and leaf, hub-spoke
   when one device connects to every other internal device and they don't interconnect,
   otherwise tiered. Set it explicitly to override.

## Editing the spec

Fix what `build` got wrong, then render again:
- a wrong role or tier: change `role` or `tier` on the node
- a missing link (no CDP on that port): add it with `"source": "manual"`
- a link that isn't real (a shared subnet on a transit VLAN): delete it
- grouping by site or security zone: set `zone` on each node

Keep hostnames and addresses exactly as they are in the configs. Redaction happens at
render time (`--redact`), never in the spec.
