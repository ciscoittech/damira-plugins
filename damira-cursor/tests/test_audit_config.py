"""#385 — block-aware audit rules. stdlib unittest, no network."""
import sys
import unittest
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PLUGIN_ROOT.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import audit_config  # noqa: E402 — path must be set first

INSECURE_CFG = (_REPO_ROOT / "scripts" / "fixtures" / "insecure-ios.cfg").read_text()
HARDENED_CFG = (_REPO_ROOT / "scripts" / "fixtures" / "hardened-ios.cfg").read_text()


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


class HardenedConfigHasNoHighFindings(unittest.TestCase):
    def test_no_high_severity_findings(self):
        findings = audit_config.audit(HARDENED_CFG)
        highs = [f for f in findings if f[0] == "HIGH"]
        self.assertEqual(highs, [], f"unexpected HIGH findings: {highs}")


if __name__ == "__main__":
    unittest.main()
