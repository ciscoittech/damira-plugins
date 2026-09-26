"""#485 gap 2 — topology diagrams: configs/ -> DiagramSpec -> Mermaid/D2/SVG/HTML (+ pptx).

Fixtures: two core routers, two access switches, CDP from core1 and LLDP from core2.
Nothing writes to the real ~/.damira: DAMIRA_LOG_DIR points at tmp.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SIBLING = PLUGIN.parent / ("damira-cursor" if PLUGIN.name == "damira" else "damira")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "topology"
sys.path.insert(0, str(PLUGIN / "scripts"))

import render_diagram  # noqa: E402
import topology  # noqa: E402

HOSTS = ("core1", "core2", "access1", "access2", "ap-lobby-01")


@pytest.fixture(autouse=True)
def _no_real_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_LOG_DIR", str(tmp_path / "logs"))


@pytest.fixture
def spec():
    return topology.build(FIXTURES)


def _assert_well_formed(data: bytes):
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(data)
    except ImportError:  # a Python whose pyexpat can't load; xmllint does the same check
        if not shutil.which("xmllint"):
            pytest.skip("no XML parser available")
        subprocess.run(["xmllint", "--noout", "-"], input=data, check=True)
        return
    assert root.tag.endswith("svg")


def _link(spec, a, b, kind=None):
    found = [lk for lk in spec["links"] if {lk["a"], lk["b"]} == {a, b} and (kind is None or lk["kind"] == kind)]
    assert len(found) == 1, f"{a}-{b}: {found}"
    return found[0]


def _end(link, node):
    return link["a_if"] if link["a"] == node else link["b_if"]


def test_cdp_lldp_and_shared_subnets_give_deduplicated_links(spec):
    up = _link(spec, "core1", "access1")
    assert (_end(up, "core1"), _end(up, "access1")) == ("Gi0/2", "Gi1/0/49")
    assert up["kind"] == "l2" and up["source"] == "cdp"
    assert _end(_link(spec, "core2", "access2"), "access2") == "Gi1/0/50"  # LLDP
    # Seen by CDP, LLDP and the shared /30: one link, labelled with its subnet.
    core = _link(spec, "core1", "core2")
    assert core["kind"] == "l3" and core["subnet"] == "10.0.0.0/30"
    assert {_end(core, "core1"), _end(core, "core2")} == {"Gi0/1"}
    assert "bgp" in core["protocols"] and "ospf" in core["protocols"]  # iBGP rides the existing link
    assert len(spec["links"]) == 8


def test_bgp_only_neighbour_is_a_bgp_edge_and_unknowns_are_external(spec):
    nodes = {n["id"]: n for n in spec["nodes"]}
    assert nodes["core1"]["role"] == "router" and nodes["access1"]["role"] == "switch"
    assert nodes["core1"]["tier"] < nodes["access1"]["tier"]
    # ebgp-multihop peer: no connected subnet, so a dashed bgp edge to an external node
    multihop = _link(spec, "core2", "ext-AS64501")
    assert multihop["kind"] == "bgp" and multihop["b_if"] == ""
    assert nodes["ext-AS64501"]["external"] and nodes["ext-AS64501"]["role"] == "cloud"
    # directly connected eBGP peer: an l3 link on the interface that holds the subnet
    isp = _link(spec, "core1", "ext-AS64500")
    assert isp["kind"] == "l3" and isp["subnet"] == "198.51.100.0/30" and _end(isp, "core1") == "Gi0/0"
    # a CDP neighbour with no config is kept, not dropped
    assert nodes["ap-lobby-01"]["external"] and nodes["ap-lobby-01"]["role"] == "ap"


def test_renders_are_self_contained_and_deterministic(spec, tmp_path):
    path = tmp_path / "topology.json"
    path.write_text(json.dumps(spec))
    first = render_diagram.render(path)
    svg = first["svg"].read_bytes()
    _assert_well_formed(svg)
    assert not re.search(rb"href|url\(|https?://(?!www\.w3\.org/2000/svg)|@import", svg)
    html = first["html"].read_text()
    assert "<svg" in html and not re.search(r"<script|<link|src=|https?://(?!www\.w3\.org/2000/svg)", html)
    again = render_diagram.render(path)
    for key in ("svg", "mmd", "d2", "html"):
        assert again[key].read_bytes() == first[key].read_bytes(), key
    # Mermaid: every node and every link
    mmd = first["mmd"].read_text()
    for node in spec["nodes"]:
        assert render_diagram.mermaid_id(node["id"]) in mmd
    assert len(re.findall(r"^\s+\S+ (?:---|-\.-)", mmd, re.M)) == len(spec["links"])
    assert "-.-" in mmd  # the bgp-only edge is dashed


def test_pptx_skip_is_graceful(spec, tmp_path, monkeypatch, capsys):
    path = tmp_path / "topology.json"
    path.write_text(json.dumps(spec))
    monkeypatch.setattr(render_diagram, "_pptx_available", lambda: False)
    monkeypatch.setattr(render_diagram.shutil, "which", lambda name: None)
    assert render_diagram.main([str(path), "--pptx"]) == render_diagram.EXIT_NO_PPTX
    assert (tmp_path / "topology.svg").is_file() and not (tmp_path / "topology.pptx").exists()
    assert "uv" in capsys.readouterr().err


def test_redacted_share_hides_hosts_and_ips_with_stable_tokens(spec, tmp_path):
    path = tmp_path / "topology.json"
    path.write_text(json.dumps(spec))
    out = render_diagram.render(path, out_dir=tmp_path / "share", redact=True)
    ips = set(re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", "".join(p.read_text() for p in FIXTURES.iterdir())))
    texts = {k: out[k].read_text() for k in ("svg", "mmd", "html", "d2")}
    for name, text in texts.items():
        for secret in (*HOSTS, "64500", "64501", "corp.example.com", *ips):
            assert secret not in text, f"{secret} leaked into {name}"
    token = out["spec"]["nodes"][0]["label"]
    assert token.startswith("HOST-")
    assert token in texts["svg"] and token in texts["html"] and token in texts["mmd"]
    assert out["pptx"] is None and not (tmp_path / "share" / "topology.json").exists()


def test_cli_build_then_render_logs_a_diagram_event(tmp_path):
    cli = [sys.executable, str(PLUGIN / "scripts" / "damira.py"), "diagram"]
    env = {"DAMIRA_LOG_DIR": str(tmp_path / "logs"), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    spec = tmp_path / "doc" / "topology.json"
    built = subprocess.run([*cli, "build", str(FIXTURES), "-o", str(spec)], env=env, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    rendered = subprocess.run([*cli, "render", str(spec)], env=env, capture_output=True, text=True)
    assert rendered.returncode == 0, rendered.stderr
    assert (tmp_path / "doc" / "index.html").is_file()
    event = json.loads((tmp_path / "logs" / "workflows.jsonl").read_text().splitlines()[-1])
    assert event["deliverable_type"] == "diagram" and event["counts"] == {"nodes": 7, "links": 8}
    assert "core1" not in json.dumps(event)


@pytest.mark.skipif(not SIBLING.is_dir(), reason="sibling plugin not checked out")
def test_plugins_ship_identical_diagram_code():
    for rel in ("scripts/topology.py", "scripts/render_diagram.py", "tests/test_diagram.py",
                "skills/generate-diagram/references/diagram-spec.md"):
        assert (PLUGIN / rel).read_bytes() == (SIBLING / rel).read_bytes(), rel
    for f in FIXTURES.iterdir():
        assert (SIBLING / "tests/fixtures/topology" / f.name).read_bytes() == f.read_bytes(), f.name
