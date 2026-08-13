---
name: upgrade-plan
description: Ask Damira to assess a version-to-version upgrade of a network platform and produce the MOP and change control. Use when the user names a product and a target release — "IOS-XE 17.6.5 to 17.9.5", "CUCM 12.5 SU7 to 15", "PAN-OS 10.2 to 11.1" — or asks what breaks, what the risk is, or how long a maintenance window needs to be. Covers CUCM, IOS-XE, IOS-XR, NX-OS, PAN-OS, FortiOS, Junos, ISE, ASA, WLC/Catalyst 9800. Not for platform-to-platform migration (CUCM to Webex Calling, on-prem to cloud) and not for diagnosing a fault after an upgrade — use troubleshoot for that.
---

# Upgrade Planning

Plan network product upgrades with structured risk assessment and produce a
production-ready MOP.

## Step 1: Gather requirements

- **Product** — CUCM, IOS-XE, PAN-OS, FortiOS, Junos, …
- **Current version** — 17.6.3, 12.5 SU7, 10.2.4
- **Target version** — 17.9.4, 15.0, 11.1.3
- **Environment** — device count, role, production/lab, user count

## Step 2: Gather evidence FIRST

Retrieve real vendor data before forming any opinion. Anything you state before this step
is recollection, not Damira's data — and version-specific bugs and advisories are exactly
what recollection gets wrong.

**Known bugs, caveats, supported upgrade path:**
```bash
~/.damira/bin/damira search-release-notes \
  "<product>" --version "<target version>"
```

**Security advisories:**
```bash
~/.damira/bin/damira search-cve \
  "<product> <target version>" --product "<product>"
```

**Both are required, and both must complete before Step 3.** An upgrade assessment
without release notes and CVEs is a guess.

**If either exits non-zero, say so plainly and stop.** Do not substitute your own
knowledge for a failed lookup and do not proceed to Step 4. An assessment built on a
failed lookup is worse than no assessment, because it reads as though it were verified.

## Step 3: Assemble the assessment yourself

Write it from the Step 2 evidence. Cite what came from vendor data; mark anything you
could not confirm as **unverified** rather than filling the gap.

1. **Upgrade path** — direct, or stepping stones required
2. **Prerequisites** — hardware, disk space, backups, licences
3. **Security advisories** — CVEs fixed or introduced in the target
4. **Known bugs** — caveats with bug IDs where available
5. **Risk level** — low/medium/high, with justification
6. **Estimated maintenance window** — realistic duration
7. **Rollback procedure** — specific steps and trigger criteria

If the searches returned little for an unusual platform or version pair, fill gaps with:

```bash
~/.damira/bin/damira upgrade-plan \
  "<product>" "<current>" "<target>" --environment "<environment>"
```

Label what it adds as unverified alongside the retrieved evidence.

## Step 4: Write the MOP

**Do not write a MOP unless Step 2 actually returned vendor data.** The templates are
local files and always available — that is precisely how an unverified plan comes to look
like a finished one. A MOP is an operational document an engineer executes against
production. If the lookups failed, say so and offer to retry.

Offer:
> "Want me to write the full MOP? I'll save it to `documents/`."

If yes:
1. Read `references/mop.md` for the required sections
2. Write the complete MOP, filling every section from the Step 2 evidence
3. Every step must have expected output
4. Rollback must have specific trigger criteria, not "if something goes wrong"
5. Mark any section you could not ground in retrieved data as
   **UNVERIFIED — confirm with vendor documentation before executing**
6. Save to `documents/{product}-upgrade-mop-{current}-to-{target}.md`

## Step 5: Change control (optional)

If asked, read `references/change-control.md`, write the change control with RFC fields,
risk matrix, and CAB checklist, and save to `documents/{product}-change-control.md`.
