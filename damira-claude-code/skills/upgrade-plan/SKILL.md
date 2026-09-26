---
name: upgrade-plan
description: Ask Damira to assess a version-to-version upgrade of a network platform and produce the MOP and change control. Use when the user names a product and a target release — "IOS-XE 17.6.5 to 17.9.5", "CUCM 12.5 SU7 to 15", "PAN-OS 10.2 to 11.1" — or asks what breaks, what the risk is, or how long a maintenance window needs to be. Covers CUCM, IOS-XE, IOS-XR, NX-OS, PAN-OS, FortiOS, Junos, ISE, ASA, WLC/Catalyst 9800. Not for platform-to-platform migration (CUCM to Webex Calling, on-prem to cloud) and not for diagnosing a fault after an upgrade — use troubleshoot for that.
allowed-tools: mcp__plugin_damira_damira__damira_search_vendor_docs, mcp__plugin_damira_damira__damira_search_release_notes, mcp__plugin_damira_damira__damira_search_cve, mcp__plugin_damira_damira__damira_upgrade_plan, mcp__damira__damira_search_vendor_docs, mcp__damira__damira_search_release_notes, mcp__damira__damira_search_cve, mcp__damira__damira_upgrade_plan
---

# Upgrade Planning

Plan network product upgrades with structured risk assessment and generate production-ready MOPs.

## Workflow

### Step 1: Gather Requirements

Ask the user for:
- **Product** — e.g., CUCM, IOS-XE, PAN-OS, FortiOS, Junos
- **Current version** — e.g., 17.6.3, 12.5 SU7, 10.2.4
- **Target version** — e.g., 17.9.4, 15.0, 11.1.3
- **Environment** — device count, role (core/edge), production/lab, user count

If they've already provided this, skip to Step 2.

### Step 2: Gather evidence FIRST

Retrieve real vendor data before forming any opinion about the upgrade. Anything you
state before this step is your own recollection, not Damira's data — and version-specific
bugs and advisories are exactly what recollection gets wrong.

**1. Known bugs, caveats, and supported upgrade path:**
Call `damira_search_release_notes` with product and target version.

**2. Security advisories:**
Call `damira_search_cve` with the target version.

**3. Install and rollback syntax (for the workbook or MOP):**
Call `damira_search_vendor_docs` for the install-mode (or platform equivalent) upgrade
and rollback procedure on the target version. The workbook's installer and rollback
commands are checked against this, and release notes rarely carry the exact syntax.

If the MCP tools aren't available, the CLI returns the same data (`<plugin root>` is two
levels above this skill's base directory; non-zero exit means the lookup failed):

```bash
python3 "<plugin root>/scripts/damira.py" search-release-notes "<product>" --version "<target>"
python3 "<plugin root>/scripts/damira.py" search-cve "<product> <target>" --product "<product>"
python3 "<plugin root>/scripts/damira.py" search-vendor-docs "<product> <target> install rollback" --vendor <vendor>
```

**IMPORTANT:** Calls 1 and 2 are required, and both must complete before Step 3. Do not
skip either — an upgrade assessment without release notes and CVEs is a guess.

**Save the evidence.** Pick a change folder, for example
`documents/{product}-{current}-to-{target}/`, and write each successful result verbatim
to its `evidence/` subfolder (`evidence/release-notes.md`, `evidence/cves.md`,
`evidence/vendor-docs-install.md`). The workbook's grounding check reads only that
folder. Paste each result unchanged: never add or reword a command in `evidence/`.

If release notes or CVEs return an error, say so plainly and stop. (If only the vendor-docs lookup fails, say so and carry on; the installer and rollback commands will be marked UNVERIFIED.) Do not substitute your own
knowledge for a failed lookup and do not proceed to Step 4 — an assessment built on a
failed lookup is worse than no assessment, because it reads as though it were verified.

### Step 3: Assemble the assessment yourself

You write the assessment from the evidence in Step 2. Cite what came from the vendor
data and mark anything you could not confirm as unverified rather than filling the gap.

1. **Upgrade Path** — direct or stepping stones required
2. **Prerequisites** — hardware, disk space, backups, licenses
3. **Security Advisories** — CVEs fixed or introduced in target version
4. **Known Bugs** — caveats from release notes, with bug IDs where available
5. **Risk Level** — low/medium/high with justification
6. **Estimated Maintenance Window** — realistic duration
7. **Rollback Procedure** — specific steps and trigger criteria

If the searches returned little for an unusual platform or version pair, call
`damira_upgrade_plan` with product, current_version, target_version, and environment to
fill gaps — and label what it adds as unverified alongside the retrieved evidence.

### Step 3b: Present the assessment and offer the deliverables

Once the evidence is in, offer both:
> "Want the upgrade workbook (.xlsx, with pre-checks, steps and post-checks) and the MOP?"

For the workbook, follow the generate-workbook skill (`../generate-workbook/SKILL.md`)
from its Step 4, using `../generate-workbook/references/workbook-upgrade.md` and this
change folder. Hand the spec fill and render to the `damira:damira-renderer` agent (Haiku) as that skill describes; keep the evidence and the decisions here. Then present the result, including the optional
redacted artifact. Then carry on with the MOP below. Both documents use the same evidence
and the same UNVERIFIED marking.

For a MOP or CAB that needs a network diagram, draw the topology from `configs/` with
the generate-diagram skill (`../generate-diagram/SKILL.md`) in the same change folder.

### Step 4: Generate MOP

**Do not write a MOP unless Step 2 actually returned vendor data.** The template tool
is local and always succeeds, so a scaffold is always available — that is precisely how
an unverified plan can come to look like a finished one. A MOP is an operational
document an engineer will execute against production. If the lookups failed, say so and
stop; offer to retry instead.

Offer:
> "Want me to write the full MOP? I'll save it to `documents/`."

If yes:
1. Read `references/mop.md` for the required sections
2. Write the complete MOP filling in every section with data from the Step 2 evidence
3. Every step must have expected output
4. Rollback must have specific trigger criteria
5. Mark any section you could not ground in retrieved data as **UNVERIFIED — confirm
   with vendor documentation before executing**
6. Save to `documents/{product}-upgrade-mop-{current}-to-{target}.md`, or `mop.md` in the
   change folder if you made one
7. Offer the Word copy for CAB submission (see **Word copy and preview** below)

### Step 5: Generate Change Control (Optional)

If the user asks:
1. Read `references/change-control.md` for the required sections
2. Write the change control with RFC fields, risk matrix, CAB checklist
3. Save to `documents/{product}-change-control.md`
4. Offer the Word copy (see **Word copy and preview** below)

### Word copy and preview

After the MOP or change control is written, offer a Word copy (.docx) for the CAB. If the
user says yes, follow `references/word-copy.md`.
