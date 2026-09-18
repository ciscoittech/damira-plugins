---
name: upgrade-plan
description: Ask Damira to assess a version-to-version upgrade of a network platform and produce the MOP and change control. Use when the user names a product and a target release — "IOS-XE 17.6.5 to 17.9.5", "CUCM 12.5 SU7 to 15", "PAN-OS 10.2 to 11.1" — or asks what breaks, what the risk is, or how long a maintenance window needs to be. Covers CUCM, IOS-XE, IOS-XR, NX-OS, PAN-OS, FortiOS, Junos, ISE, ASA, WLC/Catalyst 9800. Not for platform-to-platform migration (CUCM to Webex Calling, on-prem to cloud) and not for diagnosing a fault after an upgrade — use troubleshoot for that.
allowed-tools: mcp__plugin_damira_damira__damira_search_release_notes, mcp__plugin_damira_damira__damira_search_cve, mcp__plugin_damira_damira__damira_upgrade_plan, mcp__damira__damira_search_release_notes, mcp__damira__damira_search_cve, mcp__damira__damira_upgrade_plan
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

**IMPORTANT:** Both calls are required, and both must complete before Step 3. Do not
skip either — an upgrade assessment without release notes and CVEs is a guess.

If a tool returns an error, say so plainly and stop. Do not substitute your own
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
6. Save to `documents/{product}-upgrade-mop-{current}-to-{target}.md`

### Step 5: Generate Change Control (Optional)

If the user asks:
1. Read `references/change-control.md` for the required sections
2. Write the change control with RFC fields, risk matrix, CAB checklist
3. Save to `documents/{product}-change-control.md`
