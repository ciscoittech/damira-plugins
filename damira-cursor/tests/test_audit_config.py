"""#385 — block-aware audit rules. stdlib unittest, no network."""
import sys
import unittest
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import audit_config  # noqa: E402 — path must be set first

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
INSECURE_CFG = (_FIXTURES / "insecure-ios.cfg").read_text()
HARDENED_CFG = (_FIXTURES / "hardened-ios.cfg").read_text()


def _severities(findings):
    return [f[0] for f in findings]


def _messages(findings):
    return "\n".join(f[1] for f in findings)


class InsecureConfigFiresEveryNewRule(unittest.TestCase):
    def setUp(self):
        self.findings = audit_config.audit(INSECURE_CFG)
        self.text = _messages(self.findings)

    def test_telnet_on_vty_is_high(self):
        hits = [f for f in self.findings if "telnet" in f[1].lower()]
        self.assertTrue(hits, "expected a telnet finding")
        self.assertEqual(hits[0][0], "HIGH")

    def test_plaintext_line_password_is_high(self):
        hits = [f for f in self.findings if "plaintext" in f[1].lower()]
        self.assertTrue(hits, "expected a plaintext line password finding")
        self.assertEqual(hits[0][0], "HIGH")

    def test_missing_enable_secret_and_password_encryption_and_aaa(self):
        self.assertIn("enable secret", self.text.lower())
        self.assertIn("password-encryption", self.text.lower())
        self.assertIn("aaa new-model", self.text.lower())

    def test_vty_block_missing_access_class(self):
        hits = [f for f in self.findings if "access-class" in f[1].lower()]
        self.assertTrue(hits, "expected a missing access-class finding")
        self.assertEqual(hits[0][0], "MEDIUM")


class Issue471Rules(unittest.TestCase):
    """#471 T1.2 — the misses from the 2026-09-24 live test, plus vendor baselines."""

    def test_ios_rw_snmp_ssh_v2_and_bgp(self):
        cfg = INSECURE_CFG + "router bgp 65001\n neighbor 192.0.2.1 remote-as 65002\n"
        ids = {f["rule_id"]: f["severity"] for f in audit_config.audit_detailed(cfg)}
        self.assertEqual(ids.get("IOS-004"), "HIGH")      # RW community
        self.assertEqual(ids.get("IOS-010"), "HIGH")      # telnet on VTY
        self.assertEqual(ids.get("IOS-011"), "MEDIUM")    # no access-class
        self.assertIn("IOS-023", ids)                     # no ip ssh version 2
        self.assertIn("BGP-001", ids)                     # no neighbor password
        self.assertIn("BGP-002", ids)                     # no maximum-prefix
        self.assertNotIn("IOS-003", ids)                  # RW isn't double-reported as RO

    def test_junos_eos_nxos_baselines(self):
        junos = "set system host-name r1\nset system services telnet\nset interfaces ge-0/0/0 unit 0\n"
        eos = "management telnet\n   no shutdown\n"
        nxos = "feature telnet\nfeature bgp\n"
        self.assertEqual(audit_config.detect_vendor(junos), "junos")
        self.assertEqual(audit_config.detect_vendor(eos), "eos")
        self.assertEqual(audit_config.detect_vendor(nxos), "nxos")
        self.assertTrue({"JUN-001", "JUN-006"} <= {f["rule_id"] for f in audit_config.audit_detailed(junos)})
        self.assertIn("EOS-001", {f["rule_id"] for f in audit_config.audit_detailed(eos)})
        self.assertIn("NXOS-001", {f["rule_id"] for f in audit_config.audit_detailed(nxos)})


class VerifierFalsePositives(unittest.TestCase):
    """#471 verifier round — findings that fired on correct configs, and misses."""

    def _ids(self, cfg, vendor=""):
        return [f["rule_id"] for f in audit_config.audit_detailed(cfg, "all", vendor)]

    def test_unsupported_vendors_are_not_audited_as_ios(self):
        for cfg in ('config firewall policy\n    edit 1\n    next\nend\n',
                    "set deviceconfig system hostname fw1\nset rulebase security rules r1 action allow\n",
                    "!! IOS XR Configuration 7.9.2\nhostname xr1\n"):
            self.assertEqual(audit_config.detect_vendor(cfg), "unknown", cfg)
            self.assertEqual(self._ids(cfg), [])

    def test_bgp_peer_groups_and_templates_count(self):
        cfg = ("router bgp 65001\n template peer-session SESS\n  password s3cret\n exit-peer-session\n"
               " template peer-policy POL\n  maximum-prefix 1000\n exit-peer-policy\n"
               " neighbor UPSTREAM peer-group\n neighbor UPSTREAM password s3cret\n"
               " neighbor UPSTREAM maximum-prefix 500\n"
               " neighbor 192.0.2.1 remote-as 65002\n neighbor 192.0.2.1 peer-group UPSTREAM\n"
               " neighbor 192.0.2.5 remote-as 65003\n neighbor 192.0.2.5 inherit peer-session SESS\n"
               " neighbor 192.0.2.5 inherit peer-policy POL\n"
               " neighbor 192.0.2.9 remote-as 65004\n neighbor 192.0.2.9 password 7 0822455D0A16\n"
               " neighbor 192.0.2.9 maximum-prefix 10\n")
        findings = audit_config.audit_detailed(cfg, "security", "ios")
        ids = [f["rule_id"] for f in findings]
        self.assertNotIn("BGP-001", ids)
        self.assertNotIn("BGP-002", ids)
        type7 = [f for f in findings if "0822455D0A16" in f["message"]]
        self.assertTrue(type7 and all(f["severity"] == "MEDIUM" for f in type7))

    def test_hashed_passwords_and_platform_idioms(self):
        eos = "enable password sha512 $6$abc\nservice routing protocols model multi-agent\n"
        self.assertEqual(audit_config.detect_vendor(eos), "eos")
        self.assertNotIn("IOS-001", self._ids(eos))
        nxos = "feature bgp\nusername admin password 5 $5$abc role network-admin\nlogging logfile messages 5\n"
        ids = self._ids(nxos)
        self.assertNotIn("IOS-007", ids)
        self.assertNotIn("BP-001", ids)
        junos = "system {\n    services {\n        ssh {\n            root-login allow;\n        }\n    }\n}\n"
        self.assertIn("JUN-005", self._ids(junos))


class HardenedConfigHasNoHighFindings(unittest.TestCase):
    def test_no_high_severity_findings(self):
        findings = audit_config.audit(HARDENED_CFG)
        highs = [f for f in findings if f[0] == "HIGH"]
        self.assertEqual(highs, [], f"unexpected HIGH findings: {highs}")


if __name__ == "__main__":
    unittest.main()
