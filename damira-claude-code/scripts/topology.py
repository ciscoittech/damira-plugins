#!/usr/bin/env python3
"""Build a DiagramSpec (documents/<id>/topology.json) from a configs/ folder (#485 gap 2).

    damira diagram build configs/ -o documents/<id>/topology.json

Reads, best effort, from every file in the folder:
  - running-configs: IOS/IOS-XE/NX-OS `hostname`, `interface` + `ip address`,
    `router bgp` neighbours, OSPF (`ip ospf N area A` or `network ... area`), `switchport`;
    Junos `set` form for host-name, interface addresses and BGP neighbours
  - saved `show cdp neighbors detail` and `show lldp neighbors detail` output. The local
    device is the prompt (`core1#show cdp ...`), else the file's hostname, else its stem.

Link precedence: CDP/LLDP (physical, with both interfaces) > a /29-/31 subnet shared by
exactly two devices > a BGP session. Duplicates merge: the same core link seen by CDP,
LLDP and its /30 is one link carrying the subnet. BGP/OSPF on an existing link is kept in
`protocols`; a BGP session with no link becomes a `bgp` edge, drawn dashed. Neighbours
with no config (an AP, an ISP) become `external` nodes rather than being dropped.

The spec is the contract: the host model may fix roles, tiers, zones or links (or write
the spec from NetBox) before rendering. See skills/generate-diagram/references/diagram-spec.md.
Standard library only.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path

SPEC_VERSION = 1
ROLES = ("router", "switch", "firewall", "wlc", "ap", "server", "host", "cloud")
KINDS = ("l2", "l3", "bgp", "ospf")
_SOURCE_RANK = {"manual": 0, "cdp": 1, "lldp": 2, "subnet": 3, "bgp": 4, "ospf": 5}
_MAX_FILE = 5 * 1024 * 1024

_IF_ALIASES = {
    "gigabitethernet": "Gi", "gig": "Gi", "gi": "Gi", "tengigabitethernet": "Te", "ten": "Te", "te": "Te",
    "twentyfivegige": "Twe", "twe": "Twe", "fortygigabitethernet": "Fo", "fo": "Fo",
    "hundredgige": "Hu", "hundredgigabitethernet": "Hu", "hu": "Hu", "fastethernet": "Fa", "fa": "Fa",
    "ethernet": "Eth", "eth": "Eth", "et": "Eth", "port-channel": "Po", "po": "Po",
    "loopback": "Lo", "lo": "Lo", "vlan": "Vl", "vl": "Vl", "management": "Mgmt", "mgmt": "Mgmt",
}
_IF_SPLIT = re.compile(r"^([A-Za-z][A-Za-z-]*?)\s*(\d[\w/.:]*)$")

_PROMPT = re.compile(r"^([\w.-]+)[#>]\s*sh(?:ow)?\s+(?:cdp|lldp)\b", re.I | re.M)
_CDP_BLOCK = re.compile(r"^Device ID:", re.M)
_LLDP_BLOCK = re.compile(r"^(?:Local Intf|Local Port id):", re.M)


class SpecError(Exception):
    pass


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def short_if(name: str) -> str:
    """GigabitEthernet0/1, Gig 0/1 and Gi0/1 are the same port: Gi0/1."""
    name = (name or "").strip().rstrip(",")
    m = _IF_SPLIT.match(name)
    if not m:
        return name
    alias = _IF_ALIASES.get(m.group(1).lower())
    return f"{alias}{m.group(2)}" if alias else name


def short_host(name: str) -> str:
    """access1.corp.example.com and access1(FOC1234X) are access1. An IP stays an IP."""
    name = re.sub(r"\(.*?\)", "", (name or "").strip())
    try:
        ipaddress.ip_address(name)
        return name
    except ValueError:
        return name.split(".")[0]


def _iface_net(ip: str, mask: str) -> "ipaddress.IPv4Interface | None":
    try:
        return ipaddress.IPv4Interface(f"{ip}/{mask}" if mask else ip)
    except ValueError:
        return None


def _wildcard_net(addr: str, mask: str) -> "ipaddress.IPv4Network | None":
    """OSPF `network` takes a wildcard (0.0.0.3); some configs write a netmask. 0.0.0.0
    is a /32 here, where ipaddress would read it as a /0 netmask."""
    try:
        m = int(ipaddress.IPv4Address(mask))
        if m & (m + 1) == 0:  # contiguous wildcard
            return ipaddress.IPv4Network(f"{addr}/{32 - m.bit_length()}", strict=False)
        return ipaddress.IPv4Network(f"{addr}/{mask}", strict=False)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_config(text: str) -> dict:
    """Hostname, interfaces (ip, ospf, switchport), BGP neighbours, OSPF networks."""
    dev = {"hostname": "", "interfaces": {}, "bgp": [], "ospf_nets": [], "switchport": False,
           "routing": False, "asn": ""}
    iface = None
    section = ""
    nx_neighbor = None
    for raw in text.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s or s.startswith("!"):
            continue
        m = re.match(r"hostname\s+(\S+)", s) if not line.startswith(" ") else None
        if m or (m := re.match(r"set system host-name\s+(\S+)", s)) or (m := re.match(r"switchname\s+(\S+)", s)):
            dev["hostname"] = m.group(1).strip("\"")
            continue
        if not line.startswith((" ", "\t")):
            iface, nx_neighbor, section = None, None, ""
            if m := re.match(r"interface\s+(\S+)", s):
                iface = dev["interfaces"].setdefault(short_if(m.group(1)), {"ips": [], "ospf": False})
                section = "if"
            elif m := re.match(r"router bgp\s+(\S+)", s):
                section, dev["routing"], dev["asn"] = "bgp", True, m.group(1)
            elif re.match(r"router (?:ospf|ospfv3|eigrp|isis)\b", s):
                section, dev["routing"] = "ospf", True
            elif m := re.match(r"set interfaces (\S+) unit (\d+) family inet address (\S+)", s):
                name = m.group(1) + ("" if m.group(2) == "0" else f".{m.group(2)}")
                ip = _iface_net(m.group(3), "")
                if ip:
                    dev["interfaces"].setdefault(name, {"ips": [], "ospf": False})["ips"].append(ip)
            elif m := re.match(r"set protocols bgp group \S+ neighbor (\S+) peer-as (\S+)", s):
                dev["routing"] = True
                dev["bgp"].append({"ip": m.group(1), "asn": m.group(2)})
            elif m := re.match(r"set protocols ospf area (\S+) interface (\S+)", s):
                dev["routing"] = True
                dev["interfaces"].setdefault(m.group(2).replace(".0", ""), {"ips": [], "ospf": False})["ospf"] = True
            elif m := re.match(r"set routing-options autonomous-system (\S+)", s):
                dev["asn"] = m.group(1)
            continue
        if section == "if" and iface is not None:
            if m := re.match(r"ip address\s+(\d+\.\d+\.\d+\.\d+)(?:\s+(\d+\.\d+\.\d+\.\d+)|(/\d+))?", s):
                ip = _iface_net(m.group(1), m.group(2) or (m.group(3) or "/32")[1:])
                if ip:
                    iface["ips"].append(ip)
            elif re.match(r"ip (?:router )?ospf \S+ area|ip ospf \d+ area", s):
                iface["ospf"] = True
            elif re.match(r"switchport\b", s) and not re.match(r"switchport\s+nonegotiate$", s):
                dev["switchport"] = True
        elif section == "bgp":
            if m := re.match(r"neighbor\s+(\d+\.\d+\.\d+\.\d+)\s+remote-as\s+(\S+)", s):
                dev["bgp"].append({"ip": m.group(1), "asn": m.group(2)})
            elif m := re.match(r"neighbor\s+(\d+\.\d+\.\d+\.\d+)\s*$", s):  # NX-OS block form
                nx_neighbor = {"ip": m.group(1), "asn": ""}
                dev["bgp"].append(nx_neighbor)
            elif (m := re.match(r"remote-as\s+(\S+)", s)) and nx_neighbor is not None:
                nx_neighbor["asn"] = m.group(1)
        elif section == "ospf":
            if m := re.match(r"network\s+(\S+)\s+(\S+)\s+area\s+(\S+)", s):
                net = _wildcard_net(m.group(1), m.group(2))
                if net:
                    dev["ospf_nets"].append(net)
    for data in dev["interfaces"].values():
        if any(ip.ip in net for net in dev["ospf_nets"] for ip in data["ips"]):
            data["ospf"] = True
    return dev


def _field(block: str, pattern: str) -> str:
    m = re.search(pattern, block, re.M | re.I)
    return m.group(1).strip() if m else ""


def parse_cdp(text: str) -> "list[dict]":
    out = []
    starts = [m.start() for m in _CDP_BLOCK.finditer(text)] + [len(text)]
    for a, b in zip(starts, starts[1:]):
        block = text[a:b]
        out.append({
            "name": short_host(_field(block, r"^Device ID:\s*(\S+)")),
            "local_if": short_if(_field(block, r"^Interface:\s*([^,\n]+)")),
            "remote_if": short_if(_field(block, r"Port ID \(outgoing port\):\s*(\S+)")),
            "ip": _field(block, r"(?:IP|IPv4) [Aa]ddress:\s*(\d+\.\d+\.\d+\.\d+)"),
            "platform": re.sub(r"^cisco\s+", "", _field(block, r"^Platform:\s*([^,\n]+)"), flags=re.I),
            "caps": _field(block, r"Capabilities:\s*(.+)$"),
            "source": "cdp",
        })
    return [e for e in out if e["name"]]


def parse_lldp(text: str) -> "list[dict]":
    out = []
    starts = [m.start() for m in _LLDP_BLOCK.finditer(text)] + [len(text)]
    for a, b in zip(starts, starts[1:]):
        block = text[a:b]
        desc = _field(block, r"^System Description:\s*\n?\s*(.+)$")
        version = _field(desc + "\n", r"Version\s+([\w.()]+)")
        platform = f"IOS {version}" if version and "cisco ios" in desc.lower() else desc[:40]
        caps = _field(block, r"^Enabled Capabilities:\s*(.+)$")
        out.append({
            "name": short_host(_field(block, r"^System Name:\s*(\S+)")),
            "local_if": short_if(_field(block, r"^(?:Local Intf|Local Port id):\s*(\S+)")),
            "remote_if": short_if(_field(block, r"^Port id:\s*(\S+)")),
            "ip": _field(block, r"^\s*(?:IP|IPv4):\s*(\d+\.\d+\.\d+\.\d+)"),
            "platform": platform.strip().rstrip(","),
            "caps": {"R": "Router", "B": "Switch", "W": "WLAN"}.get(caps.split(",")[0].strip(), caps),
            "source": "lldp",
        })
    return [e for e in out if e["name"]]


def _owner(text: str, dev: dict, path: Path) -> str:
    m = _PROMPT.search(text)
    if m:
        return m.group(1)
    if dev["hostname"]:
        return dev["hostname"]
    return re.sub(r"[-_.](?:cdp|lldp|show|neighbou?rs?|sh)\b.*$", "", path.stem, flags=re.I) or path.stem


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

_ROLE_PLATFORM = (
    ("firewall", r"\basa\d*|firepower|\bftd\b|\bpa-\d|palo ?alto|fortigate|\bsrx\d|checkpoint"),
    ("wlc", r"air-ct|c9800|\bwlc\b|wireless lan controller"),
    ("ap", r"air-c?ap|\bc91\d\d|access point|\bmr\d\d"),
    ("host", r"ip phone|\bsep[0-9a-f]{12}\b|\bphone\b"),
    ("server", r"server|linux|vmware|esxi|ubuntu"),
    ("switch", r"ws-c|\bc9[2-6]\d\d|catalyst|\bn[3579]k|nexus|\bdcs-|\bqfx|\bex\d{4}|\bcbs\d"),
    ("router", r"\bisr|\basr|\bcsr|\bc8[0-5]\d\d|\bmx\d|\bptx|ios[- ]?xr|\bvmx\b"),
)
_ROLE_HOST = (
    ("firewall", r"(?:^|[-_.])(?:fw|asa|pan|fgt)(?:[-_.\d]|$)"),
    ("wlc", r"(?:^|[-_.])wlc(?:[-_.\d]|$)"),
    ("ap", r"(?:^|[-_.])ap(?:[-_.\d]|$)"),
    ("switch", r"(?:^|[-_.])(?:sw|switch|access|acc|asw|dsw|leaf|spine|dist|tor)(?:[-_.\d]|$)"),
    ("router", r"(?:^|[-_.])(?:rtr|router|r|edge|wan|pe|ce|br|gw)(?:[-_.\d]|$)"),
)


def infer_role(name: str, platform: str = "", caps: str = "", cfg: "dict | None" = None) -> str:
    for role, pattern in _ROLE_PLATFORM:
        if platform and re.search(pattern, platform, re.I):
            return role
    c = caps.lower()
    if "router" in c:
        return "router"
    if "switch" in c:
        return "switch"
    if "trans-bridge" in c or "wlan" in c:
        return "ap"
    if "phone" in c or "host" in c:
        return "host"
    for role, pattern in _ROLE_HOST:
        if re.search(pattern, name, re.I):
            return role
    if cfg:
        if cfg["switchport"] and not cfg["routing"]:
            return "switch"
        if cfg["routing"]:
            return "router"
    return "router"


def infer_tier(node: dict) -> int:
    name, role = node["id"].lower(), node["role"]
    if role == "cloud":
        return 0
    if role == "firewall":
        return 1
    if role == "router" or re.search(r"core|spine", name):
        return 2
    if role == "wlc" or re.search(r"dist|agg", name):
        return 3
    if role == "switch":
        return 4
    return 5


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class _Graph:
    def __init__(self):
        self.nodes: "dict[str, dict]" = {}
        self.links: "list[dict]" = []

    def node(self, nid: str, **fields) -> dict:
        n = self.nodes.setdefault(nid, {"id": nid, "label": fields.get("label") or nid, "role": "", "platform": "", "mgmt_ip": "",
                                        "tier": None, "zone": "", "external": False})
        for k, v in fields.items():
            if v not in ("", None) and n.get(k) in ("", None, False):
                n[k] = v
        return n

    def link(self, a, a_if, b, b_if, kind, source, subnet="", protocols=()) -> dict:
        if (b, b_if) < (a, a_if):
            a, a_if, b, b_if = b, b_if, a, a_if
        for lk in self.links:
            if (lk["a"], lk["b"]) != (a, b):
                continue
            if all(not x or not y or x == y for x, y in ((lk["a_if"], a_if), (lk["b_if"], b_if))):
                lk["a_if"], lk["b_if"] = lk["a_if"] or a_if, lk["b_if"] or b_if
                lk["subnet"] = lk["subnet"] or subnet
                if kind == "l3" and lk["kind"] in ("l2", "bgp", "ospf"):
                    lk["kind"] = "l3"
                if _SOURCE_RANK[source] < _SOURCE_RANK[lk["source"]]:
                    lk["source"] = source
                lk["protocols"] = sorted(set(lk["protocols"]) | set(protocols))
                return lk
        lk = {"a": a, "a_if": a_if, "b": b, "b_if": b_if, "subnet": subnet, "kind": kind, "source": source,
              "protocols": sorted(set(protocols))}
        self.links.append(lk)
        return lk

    def between(self, a: str, b: str) -> "list[dict]":
        return [lk for lk in self.links if {lk["a"], lk["b"]} == {a, b}]


def _read(paths: "list[Path]") -> "list[tuple[Path, str]]":
    out = []
    for p in paths:
        try:
            if p.stat().st_size > _MAX_FILE:
                continue
            out.append((p, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def _inputs(src: Path) -> "list[Path]":
    if src.is_file():
        return [src]
    if not src.is_dir():
        raise SpecError(f"{src} is not a file or folder")
    return sorted(p for p in src.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(src).parts))


def build(src, title: str = "") -> dict:
    """Parse every file under src and return a DiagramSpec dict."""
    files = _read(_inputs(Path(src)))
    devices: "dict[str, dict]" = {}
    neighbours: "list[tuple[str, dict]]" = []
    for path, text in files:
        dev = parse_config(text)
        if dev["hostname"]:
            prev = devices.get(dev["hostname"])
            if prev:  # a second file for the same device (show output saved alongside)
                prev["interfaces"].update(dev["interfaces"])
                prev["bgp"] += dev["bgp"]
            else:
                devices[dev["hostname"]] = dev
        if _CDP_BLOCK.search(text) or _LLDP_BLOCK.search(text):
            owner = _owner(text, dev, path)
            neighbours += [(owner, e) for e in parse_cdp(text) + parse_lldp(text)]
    if not devices and not neighbours:
        raise SpecError(f"no device configs or CDP/LLDP output found in {src}")

    known = {h.lower(): h for h in devices}
    for owner, _ in neighbours:
        known.setdefault(owner.lower(), owner)

    def canon(name: str) -> str:
        return known.get(name.lower(), name)

    ip_owner: "dict[str, tuple[str, str]]" = {}
    for host, dev in devices.items():
        for ifname, data in dev["interfaces"].items():
            for ip in data["ips"]:
                ip_owner.setdefault(str(ip.ip), (host, ifname))

    g = _Graph()
    facts: "dict[str, dict]" = {}  # what neighbours say about a device: platform, caps, ip
    for owner, e in neighbours:
        f = facts.setdefault(canon(e["name"]), {})
        for k in ("platform", "caps", "ip"):
            f.setdefault(k, e[k])

    for host, dev in sorted(devices.items()):
        loop = [ip for n, d in sorted(dev["interfaces"].items()) if n.startswith("Lo") for ip in d["ips"]]
        mgmt = [ip for n, d in sorted(dev["interfaces"].items()) if n.startswith(("Vl", "Mgmt")) for ip in d["ips"]]
        f = facts.get(host, {})
        first = (loop or mgmt)[:1]
        g.node(host, role=infer_role(host, f.get("platform", ""), f.get("caps", ""), dev),
               platform=f.get("platform", ""), mgmt_ip=str(first[0].ip) if first else f.get("ip", ""))

    # 1. CDP/LLDP: physical links with both interfaces
    for owner, e in neighbours:
        a, b = canon(owner), canon(e["name"])
        if a == b:
            continue
        for nid in (a, b):
            if nid not in g.nodes:
                f = facts.get(nid, {})
                g.node(nid, role=infer_role(nid, f.get("platform", ""), f.get("caps", "")),
                       platform=f.get("platform", ""), mgmt_ip=f.get("ip", ""), external=nid not in devices)
        g.link(a, e["local_if"], b, e["remote_if"], "l2", e["source"])

    # 2. A small subnet shared by exactly two devices is an L3 link
    by_net: "dict[ipaddress.IPv4Network, list]" = {}
    for host, dev in devices.items():
        for ifname, data in dev["interfaces"].items():
            if ifname.startswith("Lo"):
                continue
            for ip in data["ips"]:
                if 29 <= ip.network.prefixlen <= 31:
                    by_net.setdefault(ip.network, []).append((host, ifname, data["ospf"]))
    for net, ends in sorted(by_net.items(), key=lambda kv: (int(kv[0].network_address), kv[0].prefixlen)):
        hosts = {h for h, _, _ in ends}
        if len(ends) == 2 and len(hosts) == 2:
            (a, a_if, a_ospf), (b, b_if, b_ospf) = ends
            g.link(a, a_if, b, b_if, "l3", "subnet", str(net), ("ospf",) if a_ospf and b_ospf else ())

    # 3. BGP sessions: ride an existing link, else a connected subnet, else a bgp edge
    for host, dev in sorted(devices.items()):
        for nb in dev["bgp"]:
            peer = ip_owner.get(nb["ip"], (None, ""))[0]
            if peer == host:
                continue
            if peer is None:
                peer = f"ext-AS{nb['asn']}" if nb["asn"] else f"ext-{nb['ip']}"
                g.node(peer, label=f"AS{nb['asn']}" if nb["asn"] else nb["ip"], role="cloud",
                       mgmt_ip=nb["ip"], external=True)
            existing = g.between(host, peer)
            if existing:
                existing[0]["protocols"] = sorted(set(existing[0]["protocols"]) | {"bgp"})
                continue
            local = _connected(dev, nb["ip"])
            if local:
                g.link(host, local[0], peer, "", "l3", "bgp", str(local[1]), ("bgp",))
            else:
                g.link(host, "", peer, "", "bgp", "bgp", "", ("bgp",))

    for n in g.nodes.values():
        n["role"] = n["role"] or "router"
        n["tier"] = infer_tier(n)
    tiers = sorted({n["tier"] for n in g.nodes.values()})
    for n in g.nodes.values():
        n["tier"] = tiers.index(n["tier"])

    warnings = [f"{h}: no CDP/LLDP output mentions it; its links come only from IP subnets and BGP"
                for h in sorted(devices) if not any(h in (canon(o), canon(e["name"])) for o, e in neighbours)]
    return {
        "version": SPEC_VERSION,
        "title": title or "Network topology",
        "layout": "auto",
        "nodes": sorted(g.nodes.values(), key=lambda n: n["id"]),
        "links": sorted(g.links, key=lambda lk: (lk["a"], lk["b"], lk["a_if"], lk["b_if"], lk["kind"])),
        "zones": [],
        "warnings": warnings,
    }


def _connected(dev: dict, ip: str) -> "tuple[str, ipaddress.IPv4Network] | None":
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return None
    for ifname, data in sorted(dev["interfaces"].items()):
        for net in data["ips"]:
            if net.network.prefixlen < 32 and addr in net.network:
                return ifname, net.network
    return None


def summary(spec: dict) -> str:
    links = spec["links"]
    phys = sum(lk["source"] in ("cdp", "lldp") for lk in links)
    sub = sum(lk["source"] == "subnet" for lk in links)
    bgp = sum(lk["kind"] == "bgp" for lk in links)
    ext = sum(n["external"] for n in spec["nodes"])
    return (f"{len(spec['nodes'])} nodes ({ext} external), {len(links)} links: {phys} from CDP/LLDP, "
            f"{sub} from shared subnets, {bgp} BGP-only (dashed)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="damira diagram build",
                                description="Build topology.json (a DiagramSpec) from configs and CDP/LLDP output")
    p.add_argument("src", help="folder (or file) of running-configs and show cdp/lldp neighbors detail output")
    p.add_argument("-o", "--output", default="topology.json", help="default: ./topology.json")
    p.add_argument("--title", default="", help="diagram title (default: Network topology)")
    return p


def main(argv: "list[str] | None" = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        spec = build(a.src, a.title)
    except SpecError as exc:
        print(f"damira diagram: {exc}", file=sys.stderr)
        return 1
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Spec: {out}")
    print(summary(spec))
    for w in spec["warnings"]:
        print(f"  note: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
