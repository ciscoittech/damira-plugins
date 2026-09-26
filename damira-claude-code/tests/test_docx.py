"""#485 gap 1 — MOP / change control / incident report markdown to .docx + HTML preview.

The .docx is inspected as a zip (stdlib), so these run without python-docx in the test
interpreter; the conversion itself needs python-docx or uv and is skipped without both.
Nothing writes to the real ~/.damira: DAMIRA_LOG_DIR and HOME point at tmp.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parent.parent
_SCRIPTS = _PLUGIN / "scripts"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mop.md"
sys.path.insert(0, str(_SCRIPTS))

import md_to_docx  # noqa: E402


@pytest.fixture(autouse=True)
def _private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DAMIRA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _doc_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "documents" / "chg-0042"
    folder.mkdir(parents=True)
    shutil.copy(_FIXTURE, folder / "mop.md")
    return folder


def _can_convert() -> bool:
    return importlib.util.find_spec("docx") is not None or shutil.which("uv") is not None


@pytest.mark.skipif(not _can_convert(), reason="needs python-docx or uv")
def test_cli_writes_docx_with_heading_bordered_table_and_code_block(tmp_path):
    folder = _doc_dir(tmp_path)
    env = {**os.environ, "DAMIRA_LOG_DIR": str(tmp_path / "logs"), "HOME": str(tmp_path / "home")}
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "damira.py"), "docx", str(folder / "mop.md")],
        capture_output=True, text=True, env=env, timeout=240,
    )
    assert proc.returncode == 0, proc.stderr
    assert (folder / "mop.docx").is_file() and (folder / "mop.html").is_file()

    with zipfile.ZipFile(folder / "mop.docx") as z:
        body = z.read("word/document.xml").decode()
        core = z.read("docProps/core.xml").decode()
    assert 'w:val="Heading1"' in body and 'w:val="Heading2"' in body
    assert "<w:tbl>" in body and "<w:tcBorders>" in body, "tables carry cell borders"
    assert 'w:fill="D9E1F2"' in body, "header row is shaded"
    assert "Consolas" in body and "install add file flash:" in body, "code block is monospace"
    assert "IOS-XE 17.6.5 to 17.9.5" in core, "document title comes from the first heading"


def test_no_python_docx_and_no_uv_writes_html_only_and_exits_4(tmp_path, monkeypatch, capsys):
    folder = _doc_dir(tmp_path)
    monkeypatch.delenv(md_to_docx._REEXEC_ENV, raising=False)
    monkeypatch.setattr(md_to_docx, "_docx_available", lambda: False)
    monkeypatch.setattr(md_to_docx.shutil, "which", lambda _: None)

    code = md_to_docx.main([str(folder / "mop.md")])

    assert code == md_to_docx.EXIT_NO_DOCX == 4
    assert (folder / "mop.html").is_file()
    assert not (folder / "mop.docx").exists()
    assert "--remote" in capsys.readouterr().err


def test_preview_html_is_self_contained_and_escaped(tmp_path):
    folder = _doc_dir(tmp_path)
    result = md_to_docx.convert(folder / "mop.md", docx=False)
    page = (folder / "mop.html").read_text(encoding="utf-8")

    assert result["html"] == folder / "mop.html"
    assert "<h1>MOP: IOS-XE 17.6.5 to 17.9.5 Upgrade</h1>" in page
    assert "<table>" in page and "<th>Device</th>" in page
    assert "<pre><code>install add file" in page
    assert "<ol>" in page and "<strong>reload required</strong>" in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    # No external assets: nothing fetched from anywhere when the file is opened.
    assert not re.search(r"""\bsrc\s*=\s*["']?(https?:)?//""", page, re.I)
    assert not re.search(r"""<link\b[^>]*href\s*=\s*["']?(https?:)?//""", page, re.I)
    assert "@import" not in page and "<script" not in page


def test_redacted_preview_drops_hosts_ips_and_secrets(tmp_path, capsys):
    folder = _doc_dir(tmp_path)
    code = md_to_docx.main([str(folder / "mop.md"), "--redact", "--out-dir", str(folder / "share")])
    page = (folder / "share" / "mop.html").read_text(encoding="utf-8")

    assert code == 0
    for secret in ("chi-core-rtr-01", "chi-core-rtr-02", "10.20.30.40", "S3cr3tRO"):
        assert secret not in page, secret
    assert "HOST-1" in page and "IP-1" in page
    assert not (folder / "share" / "mop.docx").exists(), "a redacted run never writes the .docx"
    assert "Redacted:" in capsys.readouterr().out


def test_every_reference_template_converts_to_html():
    refs = sorted(_PLUGIN.glob("skills/*/references/*.md"))
    names = {r.name for r in refs}
    assert {"mop.md", "change-control.md", "incident-report.md"} <= names
    for ref in refs:
        page = md_to_docx.render_html(ref.read_text(encoding="utf-8"), ref.stem)
        assert page.startswith("<!doctype html>") and "</html>" in page, ref.name
