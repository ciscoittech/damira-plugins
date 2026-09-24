"""#379 — v0.2.1 exit-code contract. Mocks urllib; no network."""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import damira  # noqa: E402 — path must be set first


def _fake_response(payload):
    """Stand-in for the `with urlopen(...) as resp:` context manager."""
    body = json.dumps(payload).encode("utf-8")
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = body
    return cm


def _http_error(code, body=b""):
    return urllib.error.HTTPError(
        url="https://damiraai.com/api/extension/agent/chat-sync",
        code=code, msg="err", hdrs=None, fp=io.BytesIO(body),
    )


class NoAuthoritativeResultExitsNonZero(unittest.TestCase):
    def test_call_raises_with_no_answer_code(self):
        msg = f"{damira.NO_AUTHORITATIVE_RESULTS} for 'asdkjhqwe zzzz xyzzy'"
        with mock.patch("urllib.request.urlopen", return_value=_fake_response({"response": msg})):
            with self.assertRaises(damira.DamiraError) as ctx:
                damira.call("junk query", {})
        self.assertEqual(ctx.exception.code, damira.EXIT_NO_ANSWER)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_main_exits_non_zero_and_prints_to_stderr(self):
        msg = damira.NO_AUTHORITATIVE_RESULTS
        argv = ["damira", "search-cve", "asdkjhqwe zzzz xyzzy"]
        with mock.patch("urllib.request.urlopen", return_value=_fake_response({"response": msg})), \
             mock.patch.object(sys, "argv", argv), \
             self.assertRaises(SystemExit) as ctx:
            damira.main()
        self.assertNotEqual(ctx.exception.code, 0)


class GatewayTimeoutIsFriendlyAndNonZero(unittest.TestCase):
    def test_524_gives_friendly_message_and_timeout_code(self):
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(524)):
            with self.assertRaises(damira.DamiraError) as ctx:
                damira.call("question", {})
        self.assertEqual(ctx.exception.code, damira.EXIT_GATEWAY_TIMEOUT)
        self.assertIn("too long", str(ctx.exception).lower())

    def test_504_with_json_body_gives_timeout_code(self):
        body = json.dumps({"error": "NO_AUTHORITATIVE_RESULTS"}).encode("utf-8")
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(504, body)):
            with self.assertRaises(damira.DamiraError) as ctx:
                damira.call("question", {})
        self.assertEqual(ctx.exception.code, damira.EXIT_GATEWAY_TIMEOUT)


class NormalAnswerExitsZero(unittest.TestCase):
    def test_normal_answer_returns_and_main_exits_zero(self):
        with mock.patch("urllib.request.urlopen",
                         return_value=_fake_response({"response": "BGP graceful restart is..."})):
            result = damira.call("how does bgp graceful restart work", {})
        self.assertIn("BGP", result)

        argv = ["damira", "search-vendor-docs", "bgp graceful restart"]
        with mock.patch("urllib.request.urlopen",
                         return_value=_fake_response({"response": "BGP graceful restart is..."})), \
             mock.patch.object(sys, "argv", argv):
            try:
                damira.main()
            except SystemExit as exc:
                self.fail(f"main() exited non-zero on a normal answer: {exc.code}")


if __name__ == "__main__":
    unittest.main()


def test_partial_no_answer_inside_a_real_answer_is_still_an_answer():
    """Indexed docs followed by an empty web section must be returned, not exit 2."""
    body = ("## Indexed vendor documentation\n\ndocs\n## Live web results\n\n"
            + damira.NO_AUTHORITATIVE_RESULTS)
    with mock.patch("urllib.request.urlopen", return_value=_fake_response({"response": body})):
        # endswith: on the demo key the answer is prefixed with DEMO_NOTICE (#452).
        assert damira.call("Search vendor docs: x", {"mcp_tool": "search_vendor_docs"}).endswith(body)


def test_no_internal_methodology_names_ship_in_the_plugin():
    """Customers see engineering reasoning, not internal framework names."""
    root = Path(__file__).resolve().parent.parent
    leaks = [str(p.relative_to(root)) for p in root.rglob("*")
             if p.is_file() and p.suffix in {".py", ".md", ".json"}
             and "tests" not in p.parts and "GIDRP" in p.read_text(errors="ignore")]
    assert leaks == []
