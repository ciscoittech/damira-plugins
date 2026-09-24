"""#452 — key order and the demo notice. Mocks urllib; no network."""
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import damira  # noqa: E402 — path must be set first


def _answer(text):
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps({"response": text}).encode()
    return cm


def _env(monkeypatch, tmp_path, plugin="", exported=""):
    monkeypatch.setattr(damira, "CONFIG_PATH", tmp_path / "config")
    monkeypatch.setenv("DAMIRA_PLUGIN_API_KEY", plugin)
    monkeypatch.setenv("DAMIRA_API_KEY", exported)


def test_blank_plugin_setting_does_not_hide_an_exported_key(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, plugin="", exported="oncall_sk_exported0000")
    assert damira.resolve_key_source() == ("oncall_sk_exported0000", "DAMIRA_API_KEY")


def test_plugin_setting_wins_and_unsubstituted_template_is_ignored(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, plugin="oncall_sk_plugin000000", exported="oncall_sk_exported0000")
    assert damira.resolve_key_source()[1] == "plugin setting"
    _env(monkeypatch, tmp_path, plugin="${user_config.api_key}")
    assert damira.resolve_key_source()[1] == "demo"


def test_demo_answers_carry_the_notice_and_real_keys_do_not(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    with mock.patch("urllib.request.urlopen", return_value=_answer("MTU mismatch")):
        assert damira.call("q", {}).startswith(damira.DEMO_NOTICE)
    _env(monkeypatch, tmp_path, exported="oncall_sk_exported0000")
    with mock.patch("urllib.request.urlopen", return_value=_answer("MTU mismatch")):
        assert damira.call("q", {}) == "MTU mismatch"
