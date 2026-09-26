"""#475 — workflow telemetry: schema v2, the value scrub, and the opt-in upload gate.

Every test points DAMIRA_LOG_DIR at tmp, so nothing touches the real ~/.damira.
"""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import events  # noqa: E402
import validate  # noqa: E402


@pytest.fixture(autouse=True)
def _private_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_LOG_DIR", str(tmp_path / "logs"))
    for name in ("DAMIRA_TELEMETRY", "DAMIRA_ENV", "DAMIRA_EVAL_SCENARIO", "DAMIRA_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(validate.shutil, "which", lambda _name: None)


def _events(tmp_path: Path) -> "list[dict]":
    lines = (tmp_path / "logs" / "workflows.jsonl").read_text().strip().splitlines()
    return [json.loads(line) for line in lines]


def test_retry_loop_writes_v2_fields(tmp_path):
    script = tmp_path / "automation" / "nyc-core-rtr-01.py"
    script.parent.mkdir()
    usage = {"session_id": "sess-1", "model": "claude-haiku-4-5",
             "input_tokens": 12000, "output_tokens": 800}

    script.write_text("def broken(:\n")
    validate.run(script, host="claude-code", mode="hook", **usage)
    script.write_text("x = 1\n")
    validate.run(script, host="claude-code", mode="hook", **usage)

    first, second = _events(tmp_path)
    assert first["schema_version"] == 2 and first["attempt"] == 1 and first["first_pass"] is False
    assert second["loop_id"] == first["loop_id"] and len(second["loop_id"]) == 16
    assert (second["attempt"], second["retries"], second["final_status"]) == (2, 1, "pass")
    assert isinstance(second["time_to_green_ms"], int)
    assert second["model"] == "claude-haiku-4-5" and second["model_tier"] == "cheap"
    assert second["input_tokens"] == 12000 and second["est_cost_usd"] > 0
    assert second["environment"] == "production"
    raw = (tmp_path / "logs" / "workflows.jsonl").read_text()
    assert "nyc-core-rtr-01" not in raw and "sess-1" not in raw and str(tmp_path) not in raw


def test_scrub_drops_ip_hostname_and_secret_values():
    clean = events.scrub_event({
        "event": "validate", "skill": "generate-playbook",
        "vendor": "10.1.2.3",                       # IP
        "framework": "nyc-core-rtr-01",             # hostname
        "scenario_id": "token=sk-abcdefghijklmnopqrstuvwxyz",  # secret
        "model": "claude-opus-4-5", "checks": [
            {"check": "ruff", "status": "fail", "ext": ".py",
             "rule_ids": ["ruff/E501", "core1.corp.example.com"]}],
        "config_text": "hostname nyc-core-rtr-01",  # not allow-listed
    })
    assert clean["skill"] == "generate-playbook" and clean["model"] == "claude-opus-4-5"
    for gone in ("vendor", "framework", "scenario_id", "config_text"):
        assert gone not in clean
    assert clean["checks"][0]["rule_ids"] == ["ruff/E501"]


def test_flush_with_telemetry_off_makes_no_network_call(tmp_path):
    events.emit({"event": "validate", "status": "pass"})
    with mock.patch("urllib.request.urlopen") as urlopen:
        assert events.flush() == 0
    urlopen.assert_not_called()
    assert not (tmp_path / "telemetry_sent").exists()
