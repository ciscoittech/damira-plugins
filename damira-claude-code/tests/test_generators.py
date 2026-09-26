"""#473 — generator skills: the host model writes the code, `damira validate` gates it.

Shared between plugins/damira and plugins/damira-cursor (identical file in both).
"""

import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SIBLING = PLUGIN.parent / ("damira-cursor" if PLUGIN.name == "damira" else "damira")
GENERATORS = ["generate-playbook", "generate-automation", "generate-terraform",
              "generate-tests", "generate-pipeline"]

# Phrases that turned users away from mainstream frameworks before #473.
REFUSALS = [
    re.compile(r"do not use if the user wants[^.\n]*(nornir|pyats|terraform|netmiko)", re.I),
    re.compile(r"(can(no|')t|do not|don't|won't) (write|generate|produce|support)[^.\n]*"
               r"(nornir|pyats|terraform|netmiko|scrapli)", re.I),
]


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "missing YAML frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


@pytest.mark.parametrize("skill", GENERATORS)
def test_generator_has_frontmatter_and_capped_validate_loop(skill):
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    fm = _frontmatter(text)
    assert fm.get("name") == skill
    assert len(fm.get("description", "")) > 80
    if PLUGIN.name == "damira-cursor":
        assert "allowed-tools" not in fm, "Cursor skills carry no allowed-tools"
    loop = text[text.index("## Validate loop"):]
    assert f"validate <path> --skill {skill}" in loop or f"--skill {skill}" in loop
    assert "3 rounds" in loop and "skipped" in loop


def test_no_generator_refuses_a_mainstream_framework():
    for skill in GENERATORS:
        text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        for pattern in REFUSALS:
            assert not pattern.search(text), f"{skill}: {pattern.search(text).group(0)!r}"


def _tree(root: Path, pattern: str) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.glob(pattern)) if p.is_file()}


@pytest.mark.skipif(not SIBLING.is_dir(), reason="sibling plugin not checked out")
def test_plugins_ship_the_same_generators_references_and_templates():
    for skill in GENERATORS:
        assert (SIBLING / "skills" / skill / "SKILL.md").is_file(), f"{SIBLING.name} lacks {skill}"
    # Reference packs, golden templates and the render module are host-neutral: byte-identical.
    for pattern in ("skills/generate-*/references/*.md", "templates/golden/**/*"):
        mine, theirs = _tree(PLUGIN, pattern), _tree(SIBLING, pattern)
        assert mine.keys() == theirs.keys(), pattern
        assert mine == theirs, f"{pattern} differs between plugins"
    assert (PLUGIN / "scripts/golden.py").read_bytes() == (SIBLING / "scripts/golden.py").read_bytes()


def test_gitlab_example_gates_the_job_that_deploys():
    # The protected-environment check applies to the job that has `environment:`, so the
    # manual gate must sit on that job — a separate manual "approve" job is bypassable.
    yaml = pytest.importorskip("yaml")
    text = (PLUGIN / "skills/generate-pipeline/references/ci-pipelines.md").read_text()
    block = re.search(r"## GitLab CI\s+```yaml\n(.*?)```", text, re.S).group(1)
    jobs = {k: v for k, v in yaml.safe_load(block).items() if isinstance(v, dict) and "stage" in v}
    for name, job in jobs.items():
        manual = any(r.get("when") == "manual" for r in job.get("rules", []))
        assert manual == ("environment" in job), f"{name}: manual gate and environment must coincide"
    assert any("environment" in j for j in jobs.values())


def test_packs_name_the_canonical_junos_collection_and_banner_module():
    # junipernetworks.junos is a redirect shell to juniper.device; ansible-lint's
    # production profile fails fqcn[canonical] on it. junos_system has no banner option.
    for md in PLUGIN.glob("skills/generate-*/**/*.md"):
        text = md.read_text()
        assert not re.search(r"junipernetworks\.junos\.\w", text), md  # no old FQCNs
        assert "junos_system" not in text, md
    assert "juniper.device.junos_banner" in (PLUGIN / "skills/generate-playbook/SKILL.md").read_text()


def test_terraform_pack_names_real_registry_providers():
    # Verified against registry.terraform.io on 2026-09-24. The pack table is the skill's
    # namespace allowlist, so a typo pre-trusts an unclaimed namespace anyone can register.
    pack = (PLUGIN / "skills/generate-terraform/references/terraform-providers.md").read_text()
    for source in ("e-breuninger/netbox", "PaloAltoNetworks/panos", "fortinetdev/fortios",
                   "CiscoDevNet/meraki", "CiscoDevNet/iosxe", "CiscoDevNet/nxos"):
        assert f"`{source}`" in pack, source
    for wrong in ("e-breuer/", "cisco-open/meraki", "~> 0.5"):
        assert wrong not in pack, wrong


def test_junos_config_guidance_uses_real_module_options():
    # juniper.device.junos_config takes set/delete lines in `lines:` — it has no `format`.
    skill = (PLUGIN / "skills/generate-playbook/SKILL.md").read_text()
    assert "format: set" not in skill
    assert "juniper.device.junos_config" in skill
