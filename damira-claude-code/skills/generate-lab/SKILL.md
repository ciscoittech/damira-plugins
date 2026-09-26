---
name: generate-lab
description: Build a runnable ContainerLab topology with startup configs for testing or practice. Use when the user asks to lab up, simulate, reproduce, or practice a scenario — BGP convergence, OSPF multi-area, MPLS L3VPN, EVPN-VXLAN, leaf-spine — using containerised nodes (Arista cEOS, Juniper cRPD, Nokia SR Linux, FRR, VyOS). This emits ContainerLab YAML only: if the user specifically wants GNS3, EVE-NG, or Cisco CML, say so up front rather than substituting ContainerLab. To test a change in the lab before production, use lab-test-change.
allowed-tools: mcp__plugin_damira_damira__damira_search_vendor_docs, mcp__damira__damira_search_vendor_docs
---

# ContainerLab Topology Generation

Generate complete ContainerLab topologies with startup configs for lab testing.

> This skill is mostly your own work — it calls Damira only when platform syntax needs
> verifying, and `damira lab validate` checks the topology before you hand it back.
> Topology YAML and lab configs are well within your knowledge; a lookup would add
> latency without adding accuracy.

## Step 1: Gather requirements

- **Purpose** — BGP convergence, OSPF multi-area, MPLS L3VPN, EVPN-VXLAN, leaf-spine
- **Nodes** — how many, what roles
- **Node kinds**:

| Kind | Notes |
|---|---|
| `srl` | Nokia SR Linux — free, no licence |
| `frr` | FRRouting on Linux — free |
| `vyos` | VyOS — free |
| `linux` | Alpine hosts |
| `ceos` | Arista cEOS — image required |
| `crpd` | Juniper cRPD — image required |

- **Topology** — full mesh, leaf-spine, hub-spoke, ring

Prefer free kinds unless the user has the licensed images. A topology the engineer cannot
deploy is not a lab.

## Step 2: Write the topology

- top-level `name:`, then `topology:` with `nodes:` and `links:`
- `kind:` and `image:` per node (or once under `topology.kinds` / `topology.defaults`)
- `startup-config:` pointing at the config files, relative to the topology file
- every link endpoint `node:interface` names a node you defined
- management network where it matters

## Step 3: Write startup configs

Per node: interfaces with addressing that matches the links, routing protocol config
matching the lab's purpose, loopbacks for router-IDs, correct per-platform syntax
(FRR uses `frr.conf`; SR Linux uses its own CLI/JSON).

If unsure of syntax for a specific platform version, call `damira_search_vendor_docs`
with `"<feature> configuration <platform>"` and the vendor. **If the lookup fails, say so**
rather than guessing a command.

## Step 4: Save and validate

- Topology: `labs/{lab-name}.clab.yml`
- Configs: `labs/configs/{node-name}.cfg`
- README: `labs/{lab-name}-README.md`

The checker ships in this plugin, two levels above this skill's base directory:
`<plugin root>/scripts/damira.py`. It runs locally, needs no docker, and makes no API call.

```bash
python3 "<plugin root>/scripts/damira.py" lab validate labs/{lab-name}.clab.yml
```

Fix every error it names (undefined link endpoint, node without a kind, missing
startup-config) and re-run until it prints `"ok": true`.

## Step 5: Hand back the deploy instructions

```bash
cd labs/
sudo containerlab deploy -t {lab-name}.clab.yml
sudo containerlab inspect -t {lab-name}.clab.yml
docker exec -it clab-{lab-name}-{node} <cli>    # sr_cli, vtysh, Cli
sudo containerlab destroy -t {lab-name}.clab.yml --cleanup
```

Include the RAM estimate in the README. Node count times image footprint is the single
thing most likely to stop a lab from coming up. If the user wants to test a change in
this lab before production, hand off to `lab-test-change`: it deploys, applies, checks and
always destroys the lab.
