"""#477 — lab before prod: `damira lab` validates a ContainerLab topology, deploys it, applies
the change, runs the checks, and always tears the lab down.

Identical in plugins/damira and plugins/damira-cursor. No docker: the runner is faked.
"""

import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "scripts"))

import lab_run  # noqa: E402

TOPOLOGY = """\
name: bgp-change  # lab under test
topology:
  kinds:
    linux:
      image: frrouting/frr:v8.4.1
  nodes:
    r1:
      kind: linux
      startup-config: configs/r1.cfg
    r2:
      kind: linux
  links:
    - endpoints: ["r1:eth1", "r2:eth1"]
"""


def _lab(tmp_path, topology=TOPOLOGY):
    (tmp_path / "configs").mkdir(exist_ok=True)
    (tmp_path / "configs" / "r1.cfg").write_text("hostname r1\n")
    topo = tmp_path / "bgp-change.clab.yml"
    topo.write_text(topology)
    return topo


class FakeRunner:
    """Records every command; `script` maps a command substring to a result or exception."""

    def __init__(self, script=None):
        self.calls, self.script = [], script or {}

    def __call__(self, cmd, timeout=None):
        line = " ".join(cmd)
        self.calls.append(line)
        for needle, result in self.script.items():
            if needle in line:
                if isinstance(result, Exception):
                    raise result
                return subprocess.CompletedProcess(cmd, result[0], result[1], "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def ran(self, needle):
        return [c for c in self.calls if needle in c]


def _have_all(name):
    return f"/usr/local/bin/{name}"


def test_topology_validates_and_rejects_link_to_undefined_node(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)  # the stdlib reader, as on a bare host
    topo = _lab(tmp_path)
    good = lab_run.validate_topology(topo)
    assert good["ok"], good["errors"]
    assert good["name"] == "bgp-change" and good["nodes"] == ["r1", "r2"]

    bad = _lab(tmp_path, TOPOLOGY + '    - endpoints: ["r1:eth2", "r3:eth1"]\n')
    result = lab_run.validate_topology(bad)
    assert not result["ok"]
    assert any("r3" in e for e in result["errors"]), result["errors"]


def test_teardown_runs_after_apply_exception_and_after_check_failure(tmp_path):
    topo = _lab(tmp_path)
    playbook = tmp_path / "change.yml"
    playbook.write_text("- hosts: all\n  tasks: []\n")

    crash = FakeRunner({"ansible-playbook": RuntimeError("apply blew up")})
    report = lab_run.run(topo, apply=playbook, out_dir=tmp_path / "out", runner=crash,
                         which=_have_all)
    assert report["result"] == "error" and "apply blew up" in report["error"]
    assert crash.ran("destroy") and "--cleanup" in crash.ran("destroy")[0]
    assert report["teardown"]["ok"]

    checks = tmp_path / "bgp-change.checks.json"
    checks.write_text(json.dumps([{"command": "docker exec clab-{lab}-r1 vtysh -c 'show bgp summary'",
                                   "contains": "Established"}]))
    idle = FakeRunner({"show bgp summary": (0, "Neighbor 10.0.0.2 Idle\n")})
    report = lab_run.run(topo, apply=playbook, checks=checks, out_dir=tmp_path / "out",
                         before="pyats learn bgp --testbed-file clab-{lab}/testbed.yml",
                         runner=idle, which=_have_all)
    assert report["result"] == "fail"
    order = [next(i for i, c in enumerate(idle.calls) if k in c)
             for k in (" deploy ", "pyats learn", "ansible-playbook", "show bgp summary")]
    assert order == sorted(order), idle.calls
    assert idle.ran("clab-bgp-change-r1"), idle.calls
    assert not report["checks"][0]["ok"]
    assert idle.calls[-1].endswith("--cleanup"), "destroy must be the last command"
    saved = json.loads((tmp_path / "out" / "bgp-change-lab-report.json").read_text())
    assert saved["result"] == "fail" and saved["teardown"]["ok"]


def test_missing_containerlab_falls_back_to_validate_only(tmp_path):
    topo = _lab(tmp_path)
    runner = FakeRunner()
    which = lambda name: None if name in ("containerlab", "clab") else _have_all(name)  # noqa: E731

    assert lab_run.preflight(runner=runner, which=which)["mode"] == "validate-only"
    report = lab_run.run(topo, out_dir=tmp_path / "out", runner=runner, which=which)
    assert report["mode"] == "validate-only" and report["result"] == "validate-only"
    assert not runner.ran("deploy") and not runner.ran("destroy")
    md = (tmp_path / "out" / "bgp-change-lab-report.md").read_text()
    assert "validate-only" in md and "containerlab" in md
