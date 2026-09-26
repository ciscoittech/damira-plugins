"""#473 — golden templates render deterministically and pass `damira validate`.

Shared between plugins/damira and plugins/damira-cursor (identical file in both).
Nothing writes to the real ~/.damira: DAMIRA_LOG_DIR and HOME point at tmp.
"""

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "scripts"))

jinja2 = pytest.importorskip("jinja2")
yaml = pytest.importorskip("yaml")

import golden  # noqa: E402
import validate  # noqa: E402


@pytest.fixture(autouse=True)
def _private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TACACS_KEY", "golden-test-key")
    monkeypatch.setenv("SNMP_AUTH_PASS", "golden-auth-pass")
    monkeypatch.setenv("SNMP_PRIV_PASS", "golden-priv-pass")


def test_catalog_covers_every_task_on_every_platform():
    for platform in ("cisco_ios", "cisco_nxos", "arista_eos", "juniper_junos"):
        for task in ("ntp", "aaa_tacacs", "snmpv3", "syslog", "banner"):
            assert (task, platform) in golden.catalog()


@pytest.mark.parametrize("platform", ["cisco_ios", "cisco_nxos", "arista_eos", "juniper_junos"])
def test_golden_templates_render_and_pass_validate(tmp_path, platform):
    for task in ("ntp", "aaa_tacacs", "snmpv3", "syslog", "banner"):
        text = golden.render(task, platform, golden.load_vars(golden.example_vars(task)))
        assert "{{" not in text and "{%" not in text
        out = tmp_path / "configs" / f"{platform}-{task}.cfg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        result = validate.run(out)
        # Whole-config "missing X" findings are noise on a stamped fragment: a clean PASS.
        assert result["status"] == "pass", (task, platform, result["checks"])
        # A fragment is audited as its own vendor, never as IOS by default.
        assert result["vendor"] == platform, (task, platform, result["checks"])


def test_render_cli_writes_file_and_rejects_missing_vars_and_traversal(tmp_path):
    env = {"DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin"}
    cli = [sys.executable, str(PLUGIN / "scripts" / "damira.py"), "render"]
    out = tmp_path / "configs" / "r1-ntp.cfg"
    ok = subprocess.run(cli + ["ntp", "--platform", "cisco_ios", "--vars",
                               str(golden.example_vars("ntp")), "-o", str(out)],
                        capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stderr
    assert "ntp server" in out.read_text()

    empty = tmp_path / "empty.yml"
    empty.write_text("{}\n")
    missing = subprocess.run(cli + ["ntp", "--platform", "cisco_ios", "--vars", str(empty)],
                             capture_output=True, text=True, env=env)
    assert missing.returncode != 0 and "undefined" in missing.stderr.lower()

    bad = subprocess.run(cli + ["../../scripts/damira", "--platform", "cisco_ios", "--vars", str(empty)],
                         capture_output=True, text=True, env=env)
    assert bad.returncode != 0


@pytest.mark.parametrize("task,platform,bad", [
    ("ntp", "cisco_ios", {"servers": ["192.0.2.1\nusername evil privilege 15 secret x"]}),
    ("banner", "cisco_ios", {"text": "Authorized only ^\nusername backdoor privilege 15 secret 0 pwned"}),
    ("banner", "arista_eos", {"text": "hi\nEOF\nusername evil secret x"}),
    ("banner", "juniper_junos", {"text": "trailing backslash \\"}),
    ("snmpv3", "juniper_junos", {"group": "G", "user": "u", "auth_pass": 'a"b', "priv_pass": "p",
                                 "hosts": ["192.0.2.30"], "location": "x", "contact": "y"}),
])
def test_render_rejects_values_that_inject_device_lines(task, platform, bad):
    with pytest.raises(golden.GoldenError):
        golden.render(task, platform, bad)


def test_secrets_are_allowlisted_and_masked_on_stdout(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_API_KEY", "sk-leak")
    leak = tmp_path / "leak.yml"
    leak.write_text("group: G\nkey: env:DAMIRA_API_KEY\nservers: [{name: A, address: 192.0.2.1}]\n")
    with pytest.raises(golden.GoldenError):
        golden.load_vars(leak)

    env = {"DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home"),
           "PATH": "/usr/bin:/bin", "TACACS_KEY": "s3cret-tacacs"}
    cli = [sys.executable, str(PLUGIN / "scripts" / "damira.py"), "render", "aaa_tacacs",
           "--platform", "cisco_ios", "--vars", str(golden.example_vars("aaa_tacacs"))]
    shown = subprocess.run(cli, capture_output=True, text=True, env=env)
    assert shown.returncode == 0, shown.stderr
    assert "s3cret-tacacs" not in shown.stdout and "<TACACS_KEY>" in shown.stdout
    lookup = subprocess.run(cli + ["--secrets", "ansible"], capture_output=True, text=True, env=env)
    assert "s3cret-tacacs" not in lookup.stdout and "lookup('env', 'TACACS_KEY')" in lookup.stdout


def test_output_file_is_private_refuses_dangling_symlink_and_bad_vars_exit_2(tmp_path):
    env = {"DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home"),
           "PATH": "/usr/bin:/bin", "TACACS_KEY": "s3cret-tacacs"}
    cli = [sys.executable, str(PLUGIN / "scripts" / "damira.py"), "render"]
    out = tmp_path / "a.cfg"
    ok = subprocess.run(cli + ["aaa_tacacs", "--platform", "cisco_ios", "-o", str(out)],
                        capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stderr
    assert "s3cret-tacacs" in out.read_text() and (out.stat().st_mode & 0o077) == 0

    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "target.txt")
    followed = subprocess.run(cli + ["ntp", "--platform", "cisco_ios", "-o", str(link)],
                              capture_output=True, text=True, env=env)
    assert followed.returncode == 2 and not (tmp_path / "target.txt").exists()

    broken = tmp_path / "x.json"
    broken.write_text("{bad")
    bad = subprocess.run(cli + ["ntp", "--platform", "cisco_ios", "--vars", str(broken)],
                         capture_output=True, text=True, env=env)
    assert bad.returncode == 2 and "Traceback" not in bad.stderr


def test_aaa_command_authorization_last_and_snmp_traps_honour_vrf():
    for platform in ("cisco_ios", "cisco_nxos", "arista_eos"):
        aaa = golden.render("aaa_tacacs", platform, golden.load_vars(golden.example_vars("aaa_tacacs")))
        aaa_lines = [ln for ln in aaa.splitlines() if ln.startswith("aaa ")]
        # Command authorization bites the pushing session itself, so it goes last.
        assert aaa_lines[-1].startswith("aaa authorization commands"), (platform, aaa_lines)

    snmp_vars = dict(golden.load_vars(golden.example_vars("snmpv3")), vrf="management")
    assert "use-vrf management" in golden.render("snmpv3", "cisco_nxos", snmp_vars)
    for platform in ("cisco_ios", "arista_eos"):
        assert "snmp-server enable traps" in golden.render("snmpv3", platform, snmp_vars), platform


@pytest.mark.parametrize("name,text", [
    ("bad.yml", "servers: [\n"),
    ("loop.yml", "a: &x [*x]\n"),
    ("alias.yml", "a: &x [1, 2]\nb: *x\n"),
])
def test_malformed_or_aliased_yaml_vars_exit_2_with_one_line(tmp_path, name, text):
    env = {"DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin"}
    vars_file = tmp_path / name
    vars_file.write_text(text)
    r = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "damira.py"), "render", "ntp",
                        "--platform", "cisco_ios", "--vars", str(vars_file)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2, r.stderr
    assert "Traceback" not in r.stderr
    lines = r.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("damira render:"), r.stderr


@pytest.mark.parametrize("value", ["{{ lookup('pipe', 'touch /tmp/pwned473') }}", "{% raw %}x", "{# c #}",
                                   "a b", "a\x85b"])
def test_free_text_rejects_jinja_delimiters_and_unicode_line_breaks(tmp_path, value):
    vars_file = tmp_path / "v.json"
    import json
    vars_file.write_text(json.dumps({"group": "G", "user": "u", "auth_pass": "a", "priv_pass": "p",
                                     "hosts": ["192.0.2.30"], "location": value, "contact": "y"}))
    with pytest.raises(golden.GoldenError):
        golden.render("snmpv3", "cisco_ios", golden.load_vars(vars_file, secrets="ansible"))


def test_token_error_does_not_echo_an_env_resolved_value(tmp_path, monkeypatch):
    monkeypatch.setenv("NET_SECRET_HOST", "hunter2 secret")
    vars_file = tmp_path / "v.yml"
    vars_file.write_text("servers: [env:NET_SECRET_HOST]\n")
    with pytest.raises(golden.GoldenError) as exc:
        golden.render("ntp", "cisco_ios", golden.load_vars(vars_file))
    assert "hunter2" not in str(exc.value)
