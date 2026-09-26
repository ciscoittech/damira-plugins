#!/usr/bin/env python3
"""Redact a WorkbookSpec before its preview leaves the machine (#484, layer 3).

Publishing index.html as a claude.ai artifact uploads it. This runs first, on the
structured spec rather than on HTML, so a value found in an identifying column is
replaced everywhere it appears: the Summary sheet, other sheets, and command text.

Replaced with stable tokens (the same host is HOST-1 everywhere):
  - values in host/device/node/serial/site/customer-like columns and summary fields
  - IPv4 and IPv6 addresses, MAC addresses, email addresses, user@host logins
  - the secret after password/secret/key/community/token/psk keywords (quoted or not),
    including type digits, algorithm and encoding words (md5 7 ..., secret 10 $6$...,
    ENC ..., Junos ascii-text/hexadecimal-text, WLC set-key, IKEv2 local/remote keys),
    Junos *-password forms, snmp-server host communities, SNMPv3 auth/priv keys, crypt
    hashes, 0x hex keys, Bearer/JWT tokens and AWS access key IDs
  - PAN-OS pre-shared-key key -AQ==..., XML <key>/<phash>/<*community*> values,
    snmp-community-string, AireOS `config radius auth|acct add ... ascii <secret>`,
    NAME=value / name: value secrets (DAMIRA_API_KEY=, ansible_ssh_pass:), curl -u and
    URL user:pass, key-hash, private-key blocks, damira/GitHub/Slack/OpenAI-style tokens
  - description/location/contact/hostname/host-name/switchname/domain-name text,
    hostname-like names in free text (nyc-core-rtr-01, nyc-rtr1, CORE1-NYC), FQDNs,
    Cisco-style serials, and the sheet's auto_id_prefix (replaced with STEP)

Not covered: customer names in free text that sit in no identifying field. The preview review step is what catches those.

Best effort by design: the skill still shows the user the redacted preview and asks
before anything is published. Standard library only.
"""

from __future__ import annotations

import copy
import ipaddress
import re

_ID_STEMS = ("host", "device", "node", "router", "switch", "firewall", "serial", "site", "customer",
             "engineer", "owner", "contact", "circuit", "asset", "fqdn", "domain", "tenant")
# A label with one of these words describes the thing, not which one it is: Switch Model.
_NOT_ID_WORDS = {"model", "type", "platform", "version", "role", "status", "count", "sku", "pid", "image", "os"}
_LABEL_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


def _id_label(label: str) -> bool:
    """A label word starts with an identifying stem: Hostname, Mgmt Host, Site ID, but not
    Prerequisite (whose `site` would turn every status value into a HOST token)."""
    label_words = [w.lower() for w in _LABEL_WORDS.findall(label)]
    if _NOT_ID_WORDS.intersection(label_words):
        return False
    return any(w.startswith(_ID_STEMS) for w in label_words)
_IP_LABEL = re.compile(r"\bip\b|address|subnet|gateway|mgmt", re.I)

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")
# IPv6 candidates (two+ colons, hex only); each one is validated with ipaddress, so
# timestamps like 14:32:10 are left alone. The prefix length goes with the address.
_IPV6 = re.compile(r"(?<![\w:.])(?=[0-9a-f]*:[0-9a-f]*:)[0-9a-f:]{2,39}(?:/\d{1,3})?(?![\w:])", re.I)
_MAC = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b|\b(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}\b", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_LOGIN = re.compile(r"(?<=@)[a-z][\w-]*(?:\.[\w-]+)*", re.I)  # user@host without a domain
# keyword, then any number of type/algorithm/encoding words, then the secret itself.
_SECRET_KW = (r"(?:[a-z]+-)*password(?:-value)?|passwd|passphrase|shared-secret|secret|psksecret|"
              r"key-string|message-digest-key|authentication-key|auth-key|pre-shared-key|wpa-psk|psk|"
              r"key|(?:[a-z]+-)*community(?:[ -]string)?|token|(?:api|access|secret|private|auth)[_-]?(?:key|token)(?:[_-]id)?|"
              r"localizedkey")
# Words that sit between the keyword and the secret (types, encodings, Junos/WLC/IKEv2 forms).
_SECRET_MOD = (r"(?:\d{1,2}|md5|sha\S*|ascii(?:-text)?|hex(?:adecimal)?(?:-text)?|enc|encrypted|"
               r"encrypted-password|cleartext|plain|unencrypted|set-key|local|keyring|key)")
_QUOTED = r"\"[^\"\n]*\"|'[^'\n]*'"
_SECRET = re.compile(rf"(?P<kw>(?<![\w-])(?:{_SECRET_KW})(?:\s*[=:]\s*|[ \t]+)(?:(?:is|was|are)[ \t]+)?(?:{_SECRET_MOD}[ \t]+)*)"
                     rf"(?!(?:chain|generate|zeroize|pubkey-chain|import|export|config-key)\b)(?P<val>{_QUOTED}|[^\s,;\"']+)", re.I)
# A key ID, not a secret: `key 1` in a key chain, `message-digest-key 1 md5 ...`.
_KEY_ID = re.compile(r"(?:^|[\s-])(?:key|message-digest-key|authentication-key)[ \t]+$", re.I)
# IKEv2 keyring: pre-shared-key local <k1> remote <k2>
_PSK_REMOTE = re.compile(r"(?P<kw>pre-shared-key\b[^\n]*?[ \t]remote[ \t]+)(?P<val>\S+)", re.I)
# IOS/NX-OS: snmp-server host <addr> [traps|informs] [version 1|2c|3 [auth|noauth|priv]] <community>
_SNMP_HOST = re.compile(r"(?P<kw>snmp-server[ \t]+host[ \t]+\S+(?:[ \t]+(?:traps|informs|version|1|2c|3|"
                        r"auth|noauth|priv|(?:use-)?vrf[ \t]+\S+))*[ \t]+)(?P<val>[^\s\"']+)", re.I)
# SNMPv3: auth <md5|sha..> <secret> / priv <aes|des..> [128] <secret>
_SNMP = re.compile(r"(?P<kw>(?<![\w-])(?:auth[ \t]+(?:md5|sha\S*)|priv[ \t]+(?:aes\S*|3?des\S*)(?:[ \t]+\d{3})?)"
                   r"[ \t]+)(?P<val>\S+)", re.I)
_HASH = re.compile(r"\$\d{1,2}\$[^\s<]+|\b0x[0-9a-f]{8,}\b", re.I)
# XML config (PAN-OS): <key>-AQ==...</key>, <phash>...</phash>, <snmp-community-string>.
_XML_SECRET = re.compile(r"(?P<kw><(?P<tag>[\w-]*(?:key|password|secret|phash|community|psk)[\w-]*)>)"
                         r"(?P<val>[^<]+)(?=</(?P=tag)>)", re.I)
# AireOS: config radius auth|acct add <index> <ip> <port> ascii|hex <secret>
_AIREOS_RADIUS = re.compile(r"(?P<kw>config[ \t]+radius[ \t]+(?:auth|acct)[ \t]+add[ \t]+(?:\S+[ \t]+){3}"
                            r"(?:ascii|hex)[ \t]+)(?P<val>\S+)", re.I)
# NAME=value / name: value where the name ends in a secret word (DAMIRA_API_KEY=, ansible_ssh_pass:, pwd:)
_ASSIGN = re.compile(r"(?P<kw>(?<![\w-])[\w.-]{0,64}?(?:password|passwd|pass|pwd|secret|token|api[_-]?key|"
                     r"access[_-]?key|community(?:[_-]string)?)\s*[=:]\s*)(?P<val>\"[^\"\n]*\"|'[^'\n]*'|[^\s,;\"']+)",
                     re.I)
# Authorization: Basic <b64> (and other schemes); mysql -p<pw>; sshpass -p <pw>
_AUTH_HEADER = re.compile(r"(?P<kw>(?<![\w-])authorization:?[ \t]*(?:basic|digest|negotiate)[ \t]+)(?P<val>\S+)", re.I)
_CLI_PASS = re.compile(r"(?P<kw>(?<![\w-])(?:mysql\w*[^\n]*?[ \t]-p(?=[^\s-])|sshpass[ \t]+-p[ \t]*))(?P<val>\S+)")
# curl -u user:pass, scheme://user:pass@host, key-hash ssh-rsa <hash>
_CURL_USER = re.compile(r"(?P<kw>(?<![\w-])(?:-u|--user)[ \t]+[^\s:]+:)(?P<val>\S+)")
_URL_USER = re.compile(r"(?P<kw>://[^/\s:@]+:)(?P<val>[^@\s/]+)(?=@)")
_KEY_HASH = re.compile(r"(?P<kw>key-hash[ \t]+\S+[ \t]+)(?P<val>\S+)", re.I)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S)
# Bearer tokens, JWTs, AWS access key IDs, wherever they appear.
_TOKEN = re.compile(r"(?<=Bearer )\S+|\beyJ[\w-]+\.[\w-]+\.[\w-]*|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"
                    r"|\b(?:damira|oncall)_sk_\w+|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_\w+"
                    r"|\bxox[abprs]-[\w-]+|\bsk-[A-Za-z0-9_-]{20,}")
# Rest-of-line fields that carry site/customer text.
_FREE_TEXT = re.compile(r"(?P<kw>(?<![\w-])(?:description|location|contact|hostname|host-name|switchname|"
                        r"sysname|domain[- ]name|banner\s+\w+)[ \t]+)(?P<val>[^\n]+)", re.I)
# Hostname-like: 3+ dash-separated parts with a digit (nyc-core-rtr-01, DC2-SPINE-03), or
# two lettered parts with a digit (nyc-rtr1, CORE1-NYC).
_HOSTLIKE = re.compile(r"(?<![\w./@-])(?:(?=[\w-]*\d)[a-z][a-z0-9]*(?:-[a-z0-9]+){2,}"
                       r"|(?=[\w-]*\d)[a-z]{2,}\d*-[a-z]{2,}\d*)(?![\w/.-])", re.I)
_NOT_HOST = re.compile(r"^(?:aes|sha|hmac|diffie|ecdh|ecdsa|rsa|dh|group|chacha|rfc|ikev|esp|ah-|ipv|"
                       r"ospfv|snmpv|igmpv|mldv|vrrpv|port-channel|bundle-ether|tengig|gig|"
                       r"(?:HOST|IP6?|MAC|EMAIL|PERSON|SERIAL|LOGIN)-\d+$)", re.I)
# FQDNs with a real or common internal TLD (image names like x.17.09.05.SPA.bin never match).
_FQDN = re.compile(r"(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:com|net|org|io|local|lan|corp|"
                   r"internal|intra|int|home|edu|gov|mil|biz|us|uk|ca|de|eu|au|in|co|cloud)(?![\w-])", re.I)
_SERIAL = re.compile(r"\b[A-Z]{3}\d{4}[A-Z0-9]{4}\b|(?<=serial )[A-Z0-9]{6,}\b"
                     r"|(?<=serial-number )[A-Z0-9]{6,}\b|(?<=S/N )[A-Z0-9]{6,}\b")


class _Tokens:
    def __init__(self):
        self.map: "dict[str, str]" = {}
        self.counts: "dict[str, int]" = {}

    def token(self, value: str, kind: str) -> str:
        if value not in self.map:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.map[value] = f"{kind}-{self.counts[kind]}"
        return self.map[value]


def _is_placeholder(value: str) -> bool:
    return value.startswith("[") and value.endswith("]")


def _collect_identifiers(spec: dict, t: _Tokens) -> None:
    """Values in identifying columns/fields become tokens applied everywhere."""
    def consider(label: str, value) -> None:
        if not isinstance(value, str) or not value.strip() or _is_placeholder(value.strip()):
            return
        if _IP_LABEL.search(label) and _IPV4.fullmatch(value.strip()):
            t.token(value.strip(), "IP")
        elif _id_label(label) and len(value.strip()) >= 3:
            kind = "PERSON" if re.search(r"engineer|owner|contact", label, re.I) else "HOST"
            t.token(value.strip(), kind)

    for label, value in (spec.get("summary_fields") or {}).items():
        consider(str(label), value)
    for sheet in spec.get("sheets") or []:
        for header in sheet.get("headers") or []:
            key = str(header).lower().replace(" ", "_")
            for row in sheet.get("rows") or []:
                if isinstance(row, dict):
                    consider(str(header), row.get(key) or row.get(header))


def _v6(match: "re.Match") -> "str | None":
    addr = match.group(0).split("/")[0]
    if addr.strip(":") == "":
        return None
    try:
        ipaddress.IPv6Address(addr)
    except ValueError:
        return None
    return addr


def _keep(value: str) -> bool:
    return _is_placeholder(value) or value.startswith(("HOST-", "PERSON-", "IP-", "IP6-"))


def _scrub(text: str, t: _Tokens) -> str:
    for value in sorted(t.map, key=len, reverse=True):
        text = text.replace(value, t.map[value])

    def hidden(kind: str) -> str:
        t.counts[kind] = t.counts.get(kind, 0) + 1  # so the printed summary shows it
        return "[REDACTED]"

    def hide(kind: str):
        return lambda m: m.group("kw") + (m.group("val") if _keep(m.group("val")) else hidden(kind))

    def secret(m: "re.Match") -> str:
        val = m.group("val")
        if val.isdigit() and len(val) <= 3 and _KEY_ID.search(m.group("kw")):
            return m.group(0)  # key chain key ID, not a secret
        return m.group("kw") + (val if _keep(val.strip("\"'")) else hidden("SECRET"))

    text = _PRIVATE_KEY.sub(lambda m: hidden("SECRET"), text)
    text = _XML_SECRET.sub(hide("SECRET"), text)
    text = _FREE_TEXT.sub(hide("TEXT"), text)
    text = _TOKEN.sub(lambda m: hidden("SECRET"), text)
    text = _AIREOS_RADIUS.sub(hide("SECRET"), text)
    text = _AUTH_HEADER.sub(hide("SECRET"), text)
    text = _CLI_PASS.sub(hide("SECRET"), text)
    text = _CURL_USER.sub(hide("SECRET"), text)
    text = _URL_USER.sub(hide("SECRET"), text)
    text = _KEY_HASH.sub(hide("SECRET"), text)
    text = _ASSIGN.sub(hide("SECRET"), text)
    text = _SNMP_HOST.sub(hide("SECRET"), text)
    text = _SNMP.sub(hide("SECRET"), text)
    text = _SECRET.sub(secret, text)
    text = _PSK_REMOTE.sub(hide("SECRET"), text)
    text = _HASH.sub(lambda m: hidden("SECRET"), text)
    text = _EMAIL.sub(lambda m: t.token(m.group(0), "EMAIL"), text)
    text = _LOGIN.sub(lambda m: t.token(m.group(0), "HOST"), text)
    text = _MAC.sub(lambda m: t.token(m.group(0), "MAC"), text)
    text = _IPV6.sub(lambda m: t.token(m.group(0), "IP6") if _v6(m) else m.group(0), text)
    text = _IPV4.sub(lambda m: t.token(m.group(0), "IP"), text)
    text = _SERIAL.sub(lambda m: t.token(m.group(0), "SERIAL"), text)
    text = _FQDN.sub(lambda m: t.token(m.group(0), "HOST"), text)
    text = _HOSTLIKE.sub(lambda m: m.group(0) if _NOT_HOST.match(m.group(0)) else t.token(m.group(0), "HOST"),
                         text)
    return text


def _rename_headers(sheet: dict, walk) -> None:
    renames = {}
    for h in sheet.get("headers") or []:
        new = walk(str(h))
        if new != h:
            renames[h] = new
    if not renames:
        return
    sheet["headers"] = [renames.get(h, h) for h in sheet["headers"]]
    for row in sheet.get("rows") or []:
        if not isinstance(row, dict):
            continue
        for old, new in renames.items():
            for key in (str(old).lower().replace(" ", "_"), old):
                if key in row:
                    row[new.lower().replace(" ", "_")] = row.pop(key)
                    break
    for key in ("dropdowns", "formulas"):
        if isinstance(sheet.get(key), dict):
            sheet[key] = {renames.get(k, k): v for k, v in sheet[key].items()}
    for key in ("input_columns", "url_columns"):
        if isinstance(sheet.get(key), list):
            sheet[key] = [renames.get(c, c) for c in sheet[key]]
    for rule in sheet.get("conditional_rules") or []:
        if isinstance(rule, dict) and rule.get("column") in renames:
            rule["column"] = renames[rule["column"]]


def redact(spec: dict) -> "tuple[dict, dict]":
    """Return (redacted copy, {token kind: count}). The input is untouched."""
    t = _Tokens()
    _collect_identifiers(spec, t)

    def walk(node):
        if isinstance(node, str):
            return _scrub(node, t)
        if isinstance(node, list):
            return [walk(n) for n in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    out = copy.deepcopy(spec)
    # Everything the preview shows is scrubbed: labels, sheet names, headers, dropdown
    # options, formulas. Headers key the rows, so a renamed header carries its keys along.
    for key in ("title", "executive_summary"):
        if key in out:
            out[key] = walk(out[key])
    for key in ("summary_fields", "key_metrics"):
        if isinstance(out.get(key), dict):
            out[key] = {walk(str(k)): walk(v) for k, v in out[key].items()}
    for sheet in out.get("sheets") or []:
        _rename_headers(sheet, walk)
        sheet["rows"] = walk(sheet.get("rows") or [])
        if "name" in sheet:
            sheet["name"] = walk(str(sheet["name"]))
        if sheet.get("auto_id_prefix"):
            # Rendered into every row's ID; a site/customer prefix would otherwise leak.
            prefix = walk(str(sheet["auto_id_prefix"]))
            sheet["auto_id_prefix"] = prefix if prefix != sheet["auto_id_prefix"] else "STEP"
        for key in ("dropdowns", "formulas"):
            if isinstance(sheet.get(key), dict):
                sheet[key] = {k: walk(v) for k, v in sheet[key].items()}
    return out, dict(t.counts)


_MD_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_MD_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_MD_FIELD = re.compile(r"^\s*(?:[-*]\s+)?\*\*([^*:]+):?\*\*:?\s*(.+?)\s*$")


def _md_cells(line: str) -> "list[str]":
    return [c.strip().strip("`").strip() for c in _MD_ROW.match(line).group(1).split("|")]


def redact_markdown(text: str) -> "tuple[str, dict]":
    """A markdown document (MOP, change control, incident report, #485) gets the same
    treatment as a spec: values under identifying table columns and **Label:** value
    fields become tokens everywhere, then every line is scrubbed."""
    t = _Tokens()
    lines = text.splitlines()
    spec = {"summary_fields": {}, "sheets": []}
    headers: "list[str] | None" = None
    for line in lines:
        if not _MD_ROW.match(line):
            headers = None
            field = _MD_FIELD.match(line)
            if field:
                spec["summary_fields"][field.group(1).strip()] = field.group(2).split(" · ")[0].strip()
            continue
        if _MD_SEP.match(line):
            continue
        cells = _md_cells(line)
        if headers is None:
            headers = cells
            spec["sheets"].append({"headers": headers, "rows": []})
        else:
            spec["sheets"][-1]["rows"].append(dict(zip(headers, cells)))
    _collect_identifiers(spec, t)
    out = "\n".join(_scrub(line, t) for line in lines)
    return out + ("\n" if text.endswith("\n") else ""), dict(t.counts)
