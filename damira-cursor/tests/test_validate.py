"""#471 — `damira validate` and its post-write hook. Runs with or without linters installed.

External tools are replaced with fake executables on a private PATH wherever the test
depends on what a tool does, so results don't vary with the machine. Nothing writes to
the real ~/.damira: every test points DAMIRA_LOG_DIR (and HOME for subprocesses) at tmp.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parent.parent
_SCRIPTS = _PLUGIN / "scripts"
_HOOK = _PLUGIN / "hooks-handlers" / "post_write_validate.py"
sys.path.insert(0, str(_SCRIPTS))

import validate  # noqa: E402 — path must be set first

GOOD_PLAYBOOK = """---
- name: Set NTP
  hosts: routers
  gather_facts: false
  tasks:
    - name: NTP server
      cisco.ios.ios_config:
        lines:
          - ntp server 192.0.2.10
"""

# Broken without tabs: a mapping key at the wrong indent. Only a real YAML parser sees it.
BROKEN_PLAYBOOK = "---\n- name: Set NTP\n  hosts: routers\n   tasks:\n    - name: x\n"


@pytest.fixture(autouse=True)
def _private_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_LOG_DIR", str(tmp_path / "logs"))


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _fake_tool(bin_dir: Path, name: str, record: Path, exit_code: int = 0) -> None:
    """A stand-in executable that logs argv, cwd and the env vars under test."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    tool = bin_dir / name
    tool.write_text(
        "#!/bin/sh\n"
        f'echo "{name} $* | cwd=$(pwd) | TF_DATA_DIR=$TF_DATA_DIR | ANSIBLE_CONFIG=$ANSIBLE_CONFIG" >> "{record}"\n'
        f"exit {exit_code}\n"
    )
    tool.chmod(0o755)


def _no_tools(monkeypatch):
    monkeypatch.setattr(validate.shutil, "which", lambda _name: None)


def _last_event(tmp_path: Path) -> str:
    return (tmp_path / "logs" / "workflows.jsonl").read_text().strip().splitlines()[-1]


# --- basics ---------------------------------------------------------------------------

def test_valid_playbook_passes_and_broken_one_fails(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    pytest.importorskip("yaml")
    good = validate.run(_write(tmp_path, "automation/ntp.yml", GOOD_PLAYBOOK))
    assert good["status"] in ("pass", "unverified") and good["framework"] == "ansible"
    assert good["vendor"] == "cisco_ios"

    bad = validate.run(_write(tmp_path, "automation/bad.yml", BROKEN_PLAYBOOK))
    assert bad["status"] == "fail", bad


def test_missing_tools_are_skipped_with_a_hint_not_a_crash(tmp_path):
    playbook = _write(tmp_path, "automation/ntp.yml", GOOD_PLAYBOOK)
    env = {"PATH": str(tmp_path / "empty-bin"), "HOME": str(tmp_path),
           "DAMIRA_LOG_DIR": str(tmp_path / "logs")}
    proc = subprocess.run([sys.executable, str(_SCRIPTS / "validate.py"), str(playbook), "--json"],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    checks = {c["check"]: c for c in json.loads(proc.stdout)["checks"]}
    assert checks["ansible-lint"]["status"] == "skipped"
    assert "install" in checks["ansible-lint"]["hint"].lower()


# --- verifier fixes ---------------------------------------------------------------------

def test_nothing_substantive_ran_is_unverified_never_pass(tmp_path, monkeypatch):
    """#5: bare python3 — no PyYAML, no tools — must not report a broken playbook as PASS."""
    _no_tools(monkeypatch)
    monkeypatch.setitem(sys.modules, "yaml", None)  # import yaml → ImportError
    result = validate.run(_write(tmp_path, "automation/bad.yml", BROKEN_PLAYBOOK))
    assert result["status"] == "unverified", result
    assert "NOT validated" in validate.format_human(result)


def test_jinja_sandbox_blocks_python_internals(tmp_path):
    """#1: a model-written template must not execute Python, and must never pass."""
    pytest.importorskip("jinja2")
    marker = tmp_path / "pwned"
    tpl = _write(tmp_path, "automation/evil.j2",
                 "{{ ''.__class__.__mro__[1].__subclasses__() }}"
                 "{{ cycler.__init__.__globals__.os.system('touch " + str(marker) + "') }}\n")
    _write(tmp_path, "automation/vars.yml", "x: 1\n")
    result = validate.run(tpl)
    assert not marker.exists()
    assert result["status"] == "fail", result
    assert "jinja/sandbox-violation" in result["checks"][0]["rule_ids"]


def test_terraform_hook_mode_only_formats_and_cli_leaves_no_state(tmp_path, monkeypatch):
    """#2: the hook never runs init/validate; the CLI runs them outside the user's folder."""
    record = tmp_path / "calls.log"
    _fake_tool(tmp_path / "bin", "terraform", record)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    tf_dir = _write(tmp_path, "automation/tfmod.acmebank-prod/main.tf", 'variable "x" {}\n').parent
    before = sorted(p.name for p in tf_dir.iterdir())

    validate.run(tf_dir, mode="hook")
    calls = record.read_text().splitlines()
    assert [c.split()[1] for c in calls] == ["fmt"]

    record.unlink()
    validate.run(tf_dir, mode="cli")
    calls = record.read_text().splitlines()
    assert [c.split()[1] for c in calls] == ["fmt", "init", "validate"]
    for c in calls[1:]:
        assert f"cwd={tf_dir}" not in c and "TF_DATA_DIR=/" in c
    assert sorted(p.name for p in tf_dir.iterdir()) == before

    # #6: a revealing directory name never reaches the event log.
    assert "acmebank" not in _last_event(tmp_path)


def test_ansible_hook_mode_ignores_adjacent_config(tmp_path, monkeypatch):
    """#8: a written ansible.cfg / plugin dir next to the playbook is not loaded in hook mode."""
    record = tmp_path / "calls.log"
    _fake_tool(tmp_path / "bin", "ansible-playbook", record)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    playbook = _write(tmp_path, "automation/ntp.yml", GOOD_PLAYBOOK)
    _write(tmp_path, "automation/ansible.cfg", "[defaults]\nvars_plugins = ./evil\n")

    validate.run(playbook, mode="hook")
    call = record.read_text().splitlines()[0]
    assert f"cwd={playbook.parent}" not in call
    assert str(playbook) not in call  # checked from an isolated copy
    config = call.split("ANSIBLE_CONFIG=")[1].strip()
    assert config and not config.startswith(str(playbook.parent))


def test_generated_snippets_warn_and_unsupported_vendors_skip(tmp_path, monkeypatch):
    """#4: a correct IOS snippet is not a failure; FortiOS is not audited as IOS."""
    _no_tools(monkeypatch)
    snippet = _write(tmp_path, "configs/gi1.cfg",
                     "interface GigabitEthernet1/0/1\n description uplink\n no shutdown\n!\n")
    assert validate.run(snippet)["status"] != "fail"

    forti = _write(tmp_path, "configs/fw.conf",
                   'config firewall policy\n    edit 1\n        set name "web"\n    next\nend\n')
    result = validate.run(forti)
    assert result["status"] == "unverified"
    assert result["checks"][0]["rule_ids"] == ["audit/unsupported-vendor"]


def test_event_line_has_rule_ids_but_no_content(tmp_path):
    cfg = _write(tmp_path, "configs/core-rtr-01.cfg",
                 "hostname core-rtr-01\nsnmp-server community s3cretRW RW\n"
                 "line vty 0 4\n transport input telnet\n ip address 10.9.8.7 255.255.255.0\n")
    result = validate.run(cfg, host="claude-code")
    assert result["status"] == "fail"

    line = _last_event(tmp_path)
    event = json.loads(line)
    assert event["host"] == "claude-code" and event["framework"] == "config"
    assert "IOS-004" in {r for c in event["checks"] for r in c["rule_ids"]}
    for leaked in ("core-rtr-01", "s3cretRW", "10.9.8.7", "telnet", str(tmp_path)):
        assert leaked not in line, leaked


# --- the hook ---------------------------------------------------------------------------

def _run_hook(tmp_path: Path, payload: dict, *args: str) -> "subprocess.CompletedProcess":
    env = {"PATH": str(tmp_path / "empty-bin"), "HOME": str(tmp_path),
           "DAMIRA_LOG_DIR": str(tmp_path / "logs")}
    return subprocess.run([sys.executable, str(_HOOK), *args], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def test_hook_feeds_failures_back_to_the_model(tmp_path):
    cfg = _write(tmp_path, "configs/r1.cfg", "line vty 0 4\n transport input telnet\n")
    proc = _run_hook(tmp_path, {"tool_name": "Write", "tool_input": {"file_path": str(cfg)}})
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "IOS-010" in ctx and "Fix every" in ctx


def test_hook_is_silent_for_unwatched_paths_and_reads(tmp_path):
    notes = _write(tmp_path, "notes/x.yml", "a: 1\n")
    cfg = _write(tmp_path, "configs/r1.cfg", "line vty 0 4\n transport input telnet\n")
    for payload, args in [
        ({"tool_name": "Write", "tool_input": {"file_path": str(notes)}}, ()),
        ({"tool_name": "Read", "tool_input": {"file_path": str(cfg)}}, ("--host", "cursor")),
    ]:
        proc = _run_hook(tmp_path, payload, *args)
        assert proc.returncode == 0 and proc.stdout == "", payload


# A full IOS config the audit fails on its own (no AAA, no NTP, telnet on the vty).
_FULL_IOS = ("hostname r1\n!\ninterface GigabitEthernet1\n ip address 192.0.2.1 255.255.255.0\n!\n"
             "line vty 0 4\n transport input telnet\n password cisco\n!\nend\n")


def test_golden_stamp_below_line_1_is_ignored(tmp_path, monkeypatch):
    """A stamp anywhere but line 1 must not hide whole-config findings or change the vendor."""
    _no_tools(monkeypatch)
    plain = validate.run(_write(tmp_path, "configs/plain.cfg", _FULL_IOS))
    appended = validate.run(_write(tmp_path, "configs/appended.cfg",
                                   _FULL_IOS + "! Damira golden template: ntp (cisco_ios)\n"))
    assert appended["status"] == plain["status"]
    assert appended["checks"][0]["rule_ids"] == plain["checks"][0]["rule_ids"]


def test_line_1_stamp_does_not_override_a_full_config_of_another_vendor(tmp_path, monkeypatch):
    """A Junos stamp on top of a full IOS config is audited as IOS, whole-config rules included."""
    _no_tools(monkeypatch)
    plain = validate.run(_write(tmp_path, "configs/plain.cfg", _FULL_IOS))
    for stamp in ("# Damira golden template: ntp (juniper_junos)\n",
                  "! Damira golden template: ntp (cisco_ios)\n"):
        stamped = validate.run(_write(tmp_path, "configs/stamped.cfg", stamp + _FULL_IOS))
        assert stamped["vendor"] == "cisco_ios", stamp
        assert stamped["status"] == plain["status"], stamp
        assert stamped["checks"][0]["rule_ids"] == plain["checks"][0]["rule_ids"], stamp
