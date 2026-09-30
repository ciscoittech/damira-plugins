#!/usr/bin/env python3
"""UserPromptSubmit: name the matching Damira skill before Claude decides on its own.

Evidence from #561: on the same pasted Cisco config, Opus reliably reached for
`damira:config-audit` and Haiku did not — it just eyeballed the config itself and
found 5 issues where Damira's tool found 12. The gap wasn't tool availability or the
skill description; it was that a cheaper model sometimes skips the "should I use a
skill for this" step it isn't as reliable at running on its own. Confidently phrased
network-fault or upgrade prompts didn't have the same problem, so this hook exists
for the failure mode actually observed, not a general worry.

This is a nudge, not a router: it names the skill Claude would already be entitled
to pick, in plain additionalContext, and never invokes a tool, blocks the prompt, or
edits it. Local regex only — no network call, no subprocess, no file I/O beyond
stdin, so the cost is a handful of `re.search` calls (sub-millisecond; the 30s
UserPromptSubmit timeout is not a real constraint here). Whatever the outcome, the
prompt reaches Claude unmodified: the hook only ever adds a line for Claude, and
that line never repeats the user's own words back (that would be an echo, not a
hint, and worse, would surface pasted device output/secrets a second time).

Opt out with `DAMIRA_PROMPT_HINTS=0` (plugins can't yet expose a userConfig toggle
that shell-form hook commands can read directly — see device_gate.py's note on
CLAUDE_PLUGIN_OPTION_* — so this is an env var rather than a settings field).

Fails open: any exception (bad JSON, unexpected shape) exits 0 with no output,
exactly like a prompt this hook didn't recognize. A hint that occasionally
misses is fine; a hook that occasionally blocks a prompt is not.
"""

from __future__ import annotations

import json
import os
import re
import sys

# Ordered: syslog/show output is checked first because "%LINK-3-UPDOWN:
# Interface Gi0/1..." also matches the config shape below (it names an
# interface), but it's live log output, not a pasted config — troubleshoot,
# not config-audit. config-audit and upgrade-plan come next because their
# language is otherwise the most specific (a pasted config, a named
# version-to-version jump), and a generic "down"/"show" match should not
# shadow them.
#
# Revised per #561 verifier findings (2026-09-29):
# - config-audit no longer requires an audit verb. The decision is to hint
#   whenever the message contains a device configuration, full stop — a bare
#   paste ("hostname r1 / interface Gi0/0 / ...") or "can you look at this?"
#   plus a config are both real cases and neither had an audit verb.
#   _CONFIG_SHAPE also gained Junos `set system`/`set interfaces`/`set protocols`
#   forms, which the IOS-only shape missed entirely.
# - _FAULT dropped the bare `\bdown\b`/`\bflapping\b`/`\boutage\b` alternatives,
#   which matched "scroll down", "break down this essay", and "the server is
#   down, restart nginx". Fault language now has to pair with a networking noun
#   (interface, bgp, ospf, adjacency, tunnel, link, circuit, vpn, ...) or match
#   one of the existing specific phrases. It also gained an explicit
#   neighbor/adjacency-state pattern so "OSPF neighbor stuck in EXSTART" hints
#   troubleshoot even without the word "down".
# - _UPGRADE dropped the bare `\d+\.\d+ to \d+\.\d+` alternative, which matched
#   "upgrade react from 18 to 19" and "bump node 18.1 to 20.1". A version jump
#   now has to name one of the network platforms this skill actually covers
#   (IOS-XE/XR, NX-OS, PAN-OS, FortiOS, Junos, CUCM, ISE, ASA, WLC/Catalyst 9800).
# - _GENERATE dropped bare "config" from its keyword list, which matched "write
#   me a config file for eslint". It now requires a specific network
#   protocol/device keyword (bgp, vlan, acl, aaa, ...) alongside the request verb.
#
# Second pass (2026-09-29), still #561:
# - `interface \S` matched "the user interface is broken" (react) and "add an
#   interface IUser to types.ts" (TypeScript). Real device interface names
#   carry a digit or a slash (Gi0/0, GigabitEthernet0/1, Vlan10, ge-0/0/0);
#   plain words like "is" or "IUser" don't. Tightened to require one.
# - `hostname \S` matched "what's the hostname of the build server?". Real
#   config lines never follow `hostname` with a stopword; added a negative
#   lookahead for the common ones (of/is/for/in/on/the/a/an).
# - bare `access-list` matched "fix the access-list logic in our firewall
#   rules module". Real ACL lines are numbered or named-with-action; now
#   requires a number or a name followed by permit/deny.
# - _CONFIG_SHAPE gained FortiOS (`config system/firewall/router/vpn ...`)
#   and PAN-OS XML (`<entry name="...">`, `<vsys>`, `<rulebase>`) shapes,
#   which the Cisco/Junos-only shape missed entirely.
# - Added _AUDIT_LANGUAGE for "audit/harden this config please" — decision 2
#   lists audit language as a trigger, but with no config shape in the
#   message at all there was previously nothing to match on.
# - _GENERATE's trailing `(config|commands|cli)?` was optional, so "I need a
#   new router recommendation for my home" and "write a unit test for the
#   switch statement in parser.ts" matched on the net-config-term alone.
#   Rewritten as two order-independent lookaheads so the verb needs BOTH a
#   networking term AND a config/commands/cli word nearby, not just one.

_CONFIG_SHAPE = re.compile(
    r"(interface \S*[\d/]|router (bgp|ospf)|"
    r"hostname (?!(of|is|for|in|on|the|a|an)\b)\S|"
    r"enable secret|access-list\s+(\d+\b|\S+\s+(permit|deny))|"
    r"set deviceconfig|ip address \d|config[- ]?t\b|running-config|"
    r"set system (host-name|services|login|syslog|ntp|root-authentication|name-server|time-zone|domain-name)\b|"
    r"set (interfaces|protocols|routing-options|security|firewall|policy-options)\b|"
    # Junos brace form (the default `show configuration` output): a top-level stanza
    # opening at line start, or a `host-name x;` statement (#561 verifier).
    r"(?m:^\s*(system|interfaces|protocols|routing-options|security|policy-options|firewall|snmp)\s*\{)|"
    r"host-name \S+;|"
    r"config (system|firewall|router|vpn) \w+|"
    r"<entry name=|<vsys>|<rulebase>|<devices>)",
    re.IGNORECASE,
)

_AUDIT_LANGUAGE = re.compile(
    r"\b(audit|harden)\b.{0,30}\bconfig", re.IGNORECASE
)

_PLATFORM = (
    r"(ios-xe|iosxe|ios-xr|iosxr|\bios\b|nx-os|nxos|pan-os|panos|fortios|"
    r"junos|cucm|\bise\b|\basa\b|wlc|catalyst\s?9800)"
)

_UPGRADE = re.compile(
    rf"\b{_PLATFORM}\b.{{0,60}}\b\d+(\.\d+)*\b.{{0,20}}\b(to|->|→)\b.{{0,20}}\d+(\.\d+)*"
    rf"|\bupgrad(e|ing)\b.{{0,40}}\b{_PLATFORM}\b",
    re.IGNORECASE,
)

_SHOW_OUTPUT = re.compile(
    r"(show (ip )?(bgp|ospf|interface|route|running-config|cdp|arp)\b|"
    r"Neighbor\s+V\s+AS|Line protocol is|%\w+-\d-\w+:)",
    re.IGNORECASE,
)

_NET_NOUN = (
    r"(interface|link|circuit|tunnel|bgp|ospf|eigrp|adjacency|peer|neighbor|"
    r"vpn|wan|trunk|vlan|route|routing|gateway|switch|router|firewall)"
)
_FAULT = re.compile(
    rf"\b{_NET_NOUN}\b.{{0,40}}\b(down|flapping|stuck|blackhol\w*|drop\w*)\b|"
    rf"\b(down|flapping|stuck|blackhol\w*)\b.{{0,40}}\b{_NET_NOUN}\b|"
    r"can'?t (connect|reach|ping)|not (passing|forwarding) traffic|"
    r"why is [\w./-]+ down|users? (can'?t|cannot) connect|"
    r"stuck in (exstart|init|two-way|loading|attempt|exchange)",
    re.IGNORECASE,
)

_NET_CONFIG_TERM = (
    r"(bgp|ospf|eigrp|vlan|acl|access[- ]list|nat|qos|aaa|tacacs|radius|snmp|"
    r"ntp|interface|router|switch|firewall)"
)
_GENERATE = re.compile(
    rf"\b(generate|write|give me|need)\b"
    rf"(?=.{{0,60}}\b{_NET_CONFIG_TERM}\b)"
    rf"(?=.{{0,60}}\b(config|commands|cli)\b)",
    re.IGNORECASE,
)

_SKILL_ORDER = ("config-audit", "upgrade-plan", "troubleshoot", "generate-config")


def classify(prompt: str) -> str | None:
    if _SHOW_OUTPUT.search(prompt):
        return "troubleshoot"
    if _CONFIG_SHAPE.search(prompt) or _AUDIT_LANGUAGE.search(prompt):
        return "config-audit"
    if _UPGRADE.search(prompt):
        return "upgrade-plan"
    if _FAULT.search(prompt):
        return "troubleshoot"
    if _GENERATE.search(prompt):
        return "generate-config"
    return None


def main() -> None:
    if os.environ.get("DAMIRA_PROMPT_HINTS", "").strip() == "0":
        sys.exit(0)

    event = json.loads(sys.stdin.read())
    prompt = event.get("user_prompt") or event.get("prompt") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        sys.exit(0)

    skill = classify(prompt)
    if skill is None:
        sys.exit(0)

    context = (
        f"This message looks like a fit for the Damira `{skill}` skill "
        f"(run it explicitly with /damira:{skill} if you want it now)."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — fails open, never blocks the prompt
        sys.exit(0)
