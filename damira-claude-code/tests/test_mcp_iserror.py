"""#379 — MCP server maps NO_AUTHORITATIVE / gateway-timeout to isError:true.

server.py inserts scripts/ onto sys.path itself on import, so importing it here is
enough to get both modules; no network involved, damira.call is mocked directly.
"""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

import server as mcp_server  # noqa: E402 — path must be set first
import damira  # noqa: E402 — server.py's sys.path.insert makes this resolve too


def _call_tool(name, arguments):
    """Drive dispatch() the way tools/call does, capturing the isError flag."""
    try:
        text = mcp_server.dispatch(name, arguments)
        return {"isError": False, "text": text}
    except damira.DamiraError as exc:
        return {"isError": True, "text": str(exc)}


class McpMarksNonAnswersAsError(unittest.TestCase):
    def test_no_authoritative_result_is_error(self):
        with mock.patch.object(damira, "call", side_effect=damira.DamiraError(
                damira.NO_AUTHORITATIVE_RESULTS, code=damira.EXIT_NO_ANSWER)):
            result = _call_tool("damira_search_cve", {"query": "asdkjhqwe zzzz xyzzy"})
        self.assertTrue(result["isError"])

    def test_gateway_timeout_is_error(self):
        with mock.patch.object(damira, "call", side_effect=damira.DamiraError(
                "Damira took too long to answer; try a narrower question",
                code=damira.EXIT_GATEWAY_TIMEOUT)):
            result = _call_tool("damira_troubleshoot", {"problem": "ospf stuck in exstart"})
        self.assertTrue(result["isError"])

    def test_normal_answer_is_not_error(self):
        with mock.patch.object(damira, "call", return_value="BGP graceful restart is..."):
            result = _call_tool("damira_search_vendor_docs", {"query": "bgp graceful restart"})
        self.assertFalse(result["isError"])


if __name__ == "__main__":
    unittest.main()
