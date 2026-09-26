---
name: generate-workbook
description: Build an Excel workbook (.xlsx) for a network procedure — a migration, platform migration, security audit, change control, or incident-response workbook — grounded in Damira evidence, with an HTML preview. Use when the user asks for a spreadsheet, workbook, tracker, or Excel version of a migration plan, cutover, audit findings, change record, or incident timeline. For a version-to-version upgrade, use upgrade-plan (it offers the workbook itself). Not for diagnosing an active fault — use troubleshoot.
---

# Procedure workbooks

Damira supplies the structure and the evidence. You write the workbook spec. The
plugin's renderer turns it into `workbook.xlsx` and an `index.html` preview, and marks
UNVERIFIED every command cell the saved evidence doesn't contain as the same command:
whole words, on one line, not negated by a `no` in front, and ending where the cell ends
(`commit` is not backed by `commit check`, nor `reload` by `reload in 10` or `reload at 02:00`, nor a Junos `delete ... term T` by `delete ... term T from ...`: after
set/delete/deactivate/activate, `from`/`then`/`to` are part of the command). A lone verb in
a sentence backs nothing, and a cell that is only `[PLACEHOLDERS]` is never matched. A
`[PLACEHOLDER]` stands for exactly one value, and the command must end after it too
(`clear ip bgp [NEIGHBOR]` is not backed by `clear ip bgp 10.1.1.1 soft in`). A line that
warns about a command ("never", "avoid", "do not", "warning") backs nothing. These are
heuristics, so prose can still back a command now and then. It is
a text match, not a semantic check: `source-matched` means the evidence contains that
command text, not that it is right for this device. Evidence from troubleshoot,
upgrade-plan or the agent is itself model-written, so a match there is weaker than one
in vendor docs or release notes; the engineer still reviews every step. The tag is per row: one unmatched cell (a rollback,
say) marks the whole row UNVERIFIED.

## Step 1: Pick the type and read its reference

| The user wants | Reference |
|---|---|
| Hardware refresh, site move, circuit cutover | `references/workbook-migration.md` |
| Platform-to-platform (CUCM to Webex, ASA to FTD) | `references/workbook-platform-migration.md` |
| Config or posture audit with remediation tracking | `references/workbook-security-audit.md` |
| A change record with CAB fields and backout | `references/workbook-change-control.md` |
| Post-incident timeline and action items | `references/workbook-incident-response.md` |
| Version upgrade | `references/workbook-upgrade.md` (usually via upgrade-plan) |

Read the reference before writing anything. It gives the sheets, columns, and rules.

## Step 2: Choose the change folder

Everything for this piece of work lives in `documents/<id>/`, where `<id>` is short and
kebab-case, for example `documents/chi-core-refresh-2026-10/`.

```bash
mkdir -p documents/<id>/evidence
```

## Step 3: Gather evidence and save it

Run the lookups the procedure needs, writing each result straight into the evidence
folder, then read the file:

```bash
~/.damira/bin/damira search-vendor-docs "<feature> <platform> <version>" --vendor "<vendor>" \
  > documents/<id>/evidence/vendor-docs-<topic>.md; echo "exit=$?"
~/.damira/bin/damira search-release-notes "<product>" --version "<version>" \
  > documents/<id>/evidence/release-notes.md; echo "exit=$?"
~/.damira/bin/damira-audit-config configs/<device>.cfg \
  > documents/<id>/evidence/config-audit.md; echo "exit=$?"
```

**If a command prints a non-zero exit, delete that file, say the lookup failed, and
stop.** Don't fill the gap from memory. The grounding check reads only
`documents/<id>/evidence/`, so a command with no saved evidence will be marked
UNVERIFIED.

## Step 4: Write the spec

**Delegate Steps 4-5 to the `damira-renderer` subagent** (pinned to a cheap model) once the evidence is saved. Give it `documents/<id>/`, the reference file, and your decisions: environment, devices, the ordered steps, and which evidence file backs each step. It fills `workbook.json` verbatim from the evidence, runs the command below, and returns the grounding line and the UNVERIFIED rows. If the subagent isn't available, do Steps 4-5 yourself.

Write `documents/<id>/workbook.json` following the reference: the user's environment,
commands taken from the saved evidence, and `[PLACEHOLDERS]` for anything only the
engineer knows. Where you can't confirm a command, write `[VERIFY: what to check]`.

## Step 5: Render

```bash
~/.damira/bin/damira workbook documents/<id>/workbook.json
```

The renderer needs no install. It uses openpyxl if present, otherwise
`uv run --with openpyxl`.

- It prints the grounding line, for example "7 of 9 command cells matched the evidence".
  Tell the user which rows are UNVERIFIED. **Never edit a command to make it match.**
  Fix the evidence or leave the tag.
- Exit code 4 means only `index.html` was written, because there's no openpyxl and no
  uv. Suggest installing uv. `--remote` sends the spec to Damira to render, so **ask the
  user first** before re-running with it.

## Step 6: Present

1. Give the path to `workbook.xlsx`. That's the working copy.
2. Offer the preview: `documents/<id>/index.html` is self-contained. Open it in Cursor's
   browser.
3. **If this Cursor build can show a canvas**, build one from `workbook.json`, not from
   the xlsx. Keep it local:
   - a stats row: sheets, rows, % of commands matched to evidence, UNVERIFIED count
   - one table per sheet, in sheet order, with UNVERIFIED cells in red
   - a phase progress bar for each sheet with a `Status` column (Complete / total)

   No canvas available? The preview covers it. Don't mention the canvas.
