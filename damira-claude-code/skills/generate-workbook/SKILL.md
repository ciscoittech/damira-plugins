---
name: generate-workbook
description: Build an Excel workbook (.xlsx) for a network procedure — a migration, platform migration, security audit, change control, or incident-response workbook — grounded in Damira evidence, with an HTML preview. Use when the user asks for a spreadsheet, workbook, tracker, or Excel version of a migration plan, cutover, audit findings, change record, or incident timeline. For a version-to-version upgrade, use upgrade-plan (it offers the workbook itself). Not for diagnosing an active fault — use troubleshoot.
allowed-tools: mcp__plugin_damira_damira__damira_search_vendor_docs, mcp__plugin_damira_damira__damira_search_release_notes, mcp__plugin_damira_damira__damira_search_cve, mcp__plugin_damira_damira__damira_troubleshoot, mcp__plugin_damira_damira__analyze_config, mcp__damira__damira_search_vendor_docs, mcp__damira__damira_search_release_notes, mcp__damira__damira_search_cve, mcp__damira__damira_troubleshoot, mcp__damira__analyze_config
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
kebab-case, for example `documents/chi-core-refresh-2026-10/`. Create
`documents/<id>/evidence/`.

## Step 3: Gather evidence and save it

Call the Damira tools the procedure needs: vendor docs for command syntax, release
notes and CVEs for anything version-specific, `analyze_config` for an audit, and
troubleshoot output for an incident. **Save each successful result verbatim** to
`documents/<id>/evidence/<source>.md` (for example `vendor-docs-cutover.md`). The
grounding check reads only that folder, so a command you don't save evidence for will
be marked UNVERIFIED. Here you write those files yourself (MCP results can't be
redirected), so the check is only as honest as the copy: paste the tool result
unchanged, and never add, fix, or reword a command in `evidence/`.

If a lookup errors, say so and stop. Don't fill the gap from memory. A workbook built on
a failed lookup reads as though it were verified.

## Step 4: Write the spec

**Delegate Steps 4-5 to the `damira:damira-renderer` agent** (it runs on Haiku) once the evidence is saved. Give it `documents/<id>/`, the reference file, and your decisions: environment, devices, the ordered steps, and which evidence file backs each step. It fills `workbook.json` verbatim from the evidence, runs the command below, and returns the grounding line and the UNVERIFIED rows. If the agent isn't available, do Steps 4-5 yourself.

Write `documents/<id>/workbook.json` following the reference: the user's environment,
commands taken from the saved evidence, and `[PLACEHOLDERS]` for anything only the
engineer knows. Where you can't confirm a command, write `[VERIFY: what to check]`.

## Step 5: Render

```bash
python3 "<plugin root>/scripts/damira.py" workbook documents/<id>/workbook.json
```

`<plugin root>` is two levels above this skill's base directory. The renderer needs no
install. It uses openpyxl if present, otherwise `uv run --with openpyxl`.

- It prints the grounding line, for example "7 of 9 command cells matched the evidence".
  Tell the user which rows are UNVERIFIED. **Never edit a command to make it match.**
  Fix the evidence or leave the tag.
- Exit code 4 means only `index.html` was written, because there's no openpyxl and no
  uv. Suggest installing uv. `--remote` sends the spec to Damira to render, so **ask the
  user first** before re-running with it.

## Step 6: Present

1. Give the path to `workbook.xlsx`. That's the working copy.
2. Offer the preview: `documents/<id>/index.html` is self-contained and opens in any
   browser, including the Browser pane.
3. **Optional: share as an artifact.** Only if the Artifact tool is available in this
   session (it isn't on ZDR, HIPAA, or API-key organisations; skip this step silently
   there), and only if the user says yes. Publishing uploads the page to claude.ai. Never
   publish the unredacted preview:
   ```bash
   python3 "<plugin root>/scripts/damira.py" workbook documents/<id>/workbook.json \
     --redact --out-dir documents/<id>/share
   ```
   Show the user what was redacted (the command prints the counts), ask them to confirm
   `documents/<id>/share/index.html` has nothing sensitive left, then publish that file.
   Artifacts are private until the user shares them.
