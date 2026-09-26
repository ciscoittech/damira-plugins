---
name: generate-diagram
description: Draw a network topology diagram from the device configs and saved show cdp/lldp neighbors detail output in configs/ — an SVG, a self-contained HTML preview, Mermaid and D2, and optionally an editable PowerPoint slide. Use when the user asks to draw, map, diagram or visualise the topology, the network, the links between devices, or wants a network diagram for a MOP, a change record, an incident report or a deck. Not for diagnosing a fault (use troubleshoot) or reviewing a config's security (use config-audit).
---

# Topology diagrams

The plugin's scripts parse the configs into a spec (`topology.json`) and draw it. You
review the spec with the engineer, fix what the configs can't tell you, and present the
result. Everything runs locally and needs no install; no Damira API call is made.

## Step 1: Choose the folder and check the inputs

Work in `documents/<id>/`, where `<id>` is short and kebab-case, such as
`documents/chi-core-topology/`. The inputs are the files in `configs/`: running-configs
(IOS, IOS-XE, NX-OS, Junos `set` form) and saved `show cdp neighbors detail` or
`show lldp neighbors detail` output, one file per device.

Configs alone give links only where two devices share a /29 to /31 subnet, plus BGP
sessions. If there is no CDP/LLDP output, say so and suggest the engineer saves
`show cdp neighbors detail` (or LLDP) from each device into `configs/`. Give the command;
don't run it on devices.

No configs at all, but the engineer describes the network or a source of truth such as
NetBox is connected? Write `documents/<id>/topology.json` yourself following
`references/diagram-spec.md`, and skip to Step 4.

## Step 2: Build the spec

`<plugin root>` is two levels above this skill's base directory.

```bash
python3 "<plugin root>/scripts/damira.py" diagram build configs/ -o documents/<id>/topology.json
```

It prints what it found, for example "7 nodes (3 external), 8 links: 6 from CDP/LLDP, 0
from shared subnets, 1 BGP-only (dashed)", plus a note for every device no CDP/LLDP
output mentions.

## Step 3: Review the links with the engineer

Read `topology.json` and summarise it in a short table: each link's two ends with their
interfaces, and how it was found. Point out what is inferred rather than seen:
- links with `source` `subnet` or `bgp` (no CDP/LLDP behind them)
- dashed `bgp` edges and `external` nodes
- devices the notes say no neighbour output mentions

Ask whether anything is missing or wrong. Apply the answers by editing the spec (see
`references/diagram-spec.md`): set `role`, `tier` or `zone`, add links with
`"source": "manual"`, delete links that aren't real. Never invent a link or an interface
the engineer or the evidence didn't give you.

## Step 4: Render

```bash
python3 "<plugin root>/scripts/damira.py" diagram render documents/<id>/topology.json
```

This writes `topology.svg`, `index.html`, `topology.mmd` and `topology.d2` next to the
spec. The same spec always gives the same files.

Add `--pptx` if the engineer wants an editable slide (for a deck or a CAB). It uses
python-pptx if present, otherwise `uv run --with python-pptx`. Exit code 4 means no slide
was written because neither is available; everything else is. Suggest installing uv.

## Step 5: Present

1. Give the paths: `topology.svg` for documents, `index.html` for viewing (the diagram
   plus device and link tables; self-contained, opens in any browser, including the
   Browser pane).
2. Show the Mermaid inline in a ```mermaid block, so the engineer sees it in chat and can
   paste it into a wiki or a ticket.
3. **Optional: share as an artifact.** Only if the Artifact tool is available in this
   session (it isn't on ZDR, HIPAA, or API-key organisations; skip this step silently
   there), and only if the user says yes. Publishing uploads the page to claude.ai. Never
   publish the unredacted preview:
   ```bash
   python3 "<plugin root>/scripts/damira.py" diagram render documents/<id>/topology.json \
     --redact --out-dir documents/<id>/share
   ```
   Hostnames, AS numbers, management IPs and subnets become tokens (HOST-1, IP-2, NET-1),
   the same in every file. Show the user the redaction counts the command prints, ask them
   to check `documents/<id>/share/index.html` for anything left, then publish that file.
   Artifacts are private until the user shares them.

When a MOP, change control or incident report in the same folder needs the diagram,
reference `topology.svg` or paste the Mermaid into it.
