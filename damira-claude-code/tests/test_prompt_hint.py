"""Regression tests for the UserPromptSubmit skill-hint hook.

MVP coverage (#561): one parametrized case per class of message the hook must
route (or must not hint on), plus the safety properties that matter more than
any single match — it never blocks, never echoes the prompt back, respects
the opt-out, and fails open on bad input.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks-handlers" / "prompt_hint.py"


def run_hook(prompt: str, opt_out: bool = False):
    env = {"PATH": "/usr/bin:/bin"}
    if opt_out:
        env["DAMIRA_PROMPT_HINTS"] = "0"
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"user_prompt": prompt}),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout.strip()


# Prompt -> the skill name that must appear in the hint. Each case documents,
# in one line, the real #561 finding it locks in.
_HINTS = [
    pytest.param(
        "can you review this and harden it:\nhostname r1\nenable secret 0 cisco123\ninterface Gi0/0",
        "config-audit",
        id="pasted-ios-config-with-audit-verb",
    ),
    pytest.param(
        "hostname r1\ninterface Gi0/0\n ip address 10.0.0.1 255.255.255.0\ntransport input telnet",
        "config-audit",
        id="bare-pasted-config-no-verb",
    ),
    pytest.param(
        "can you look at this?\nhostname r1\ninterface Gi0/0\nenable secret 0 cisco123",
        "config-audit",
        id="vague-instruction-plus-config",
    ),
    pytest.param(
        "harden this junos config:\nset system services ssh\nset interfaces ge-0/0/0 unit 0",
        "config-audit",
        id="junos-config-shape",
    ),
    pytest.param(
        'config system interface\nedit "port1"\nset ip 10.0.0.1 255.255.255.0\nnext\nend',
        "config-audit",
        id="fortios-config-shape",
    ),
    pytest.param(
        '<devices><entry name="localhost.localdomain"><vsys><entry name="vsys1">',
        "config-audit",
        id="panos-xml-config-shape",
    ),
    pytest.param(
        "audit/harden this config please",
        "config-audit",
        id="audit-language-with-no-paste",
    ),
    pytest.param(
        "we need to upgrade IOS-XE 17.6.5 to 17.9.5, what breaks?",
        "upgrade-plan",
        id="named-platform-version-jump",
    ),
    pytest.param(
        "why is BGP down between P1 and PE1, the adjacency is stuck",
        "troubleshoot",
        id="fault-language-with-network-noun",
    ),
    pytest.param(
        "OSPF neighbor stuck in EXSTART on gi0/1",
        "troubleshoot",
        id="adjacency-state-without-the-word-down",
    ),
    pytest.param(
        "%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down",
        "troubleshoot",
        id="syslog-line-not-config-shape",
    ),
    pytest.param(
        "generate a BGP config for a Cisco 9300 running IOS-XE",
        "generate-config",
        id="generate-verb-plus-protocol-plus-config-word",
    ),
    pytest.param(
        "Audit this:\nsystem {\n    host-name r1;\n    services { telnet; }\n}\n"
        "interfaces {\n    ge-0/0/0 { unit 0 { family inet { address 10.0.0.1/30; } } }\n}",
        "config-audit",
        id="junos-brace-form-show-configuration",
    ),
]


@pytest.mark.parametrize("prompt,skill", _HINTS)
def test_hints_the_right_skill(prompt, skill):
    code, out = run_hook(prompt)
    assert code == 0
    assert skill in out
    assert f"/damira:{skill}" in out


# Prompts that must never produce a hint, each pinned to the specific false
# positive #561 found for it.
_NO_HINTS = [
    pytest.param("what's a good name for my cat", id="unrelated-prompt"),
    pytest.param("scroll down to the bottom of the page", id="scroll-down-not-fault"),
    pytest.param("break down this essay for me", id="break-down-not-fault"),
    pytest.param("the server is down, restart nginx", id="generic-server-no-network-noun"),
    pytest.param("upgrade react from 18 to 19", id="generic-upgrade-no-platform"),
    pytest.param("bump node 18.1 to 20.1", id="generic-version-jump-no-platform"),
    pytest.param("write me a config file for eslint", id="generic-config-word-no-net-term"),
    pytest.param(
        "the user interface is broken in my react app",
        id="ui-interface-not-device-interface",
    ),
    pytest.param(
        "what's the hostname of the build server?",
        id="hostname-question-not-config-line",
    ),
    pytest.param(
        "add an interface IUser to types.ts",
        id="typescript-interface-not-device-interface",
    ),
    pytest.param(
        "fix the access-list logic in our firewall rules module",
        id="access-list-prose-not-acl-line",
    ),
    pytest.param(
        "I need a new router recommendation for my home",
        id="need-router-with-no-config-request",
    ),
    pytest.param(
        "write a unit test for the switch statement in parser.ts",
        id="write-switch-statement-not-device-switch",
    ),
    pytest.param("set system time in the docker container", id="set-system-time-docker-not-junos"),
]


@pytest.mark.parametrize("prompt", _NO_HINTS)
def test_produces_no_hint(prompt):
    code, out = run_hook(prompt)
    assert code == 0
    assert out == ""


def test_never_echoes_the_prompt_text():
    secret_looking_prompt = "audit this config: enable secret 0 SuperSecretPassw0rd!! interface Gi0/0"
    code, out = run_hook(secret_looking_prompt)
    assert code == 0
    assert "SuperSecretPassw0rd" not in out


def test_opt_out_env_var_disables_the_hook():
    code, out = run_hook("why is BGP down, adjacency is stuck", opt_out=True)
    assert code == 0
    assert out == ""


def test_malformed_input_fails_open_not_blocking():
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
