# Word copy and preview

Used from Step 4/5 of the upgrade-plan skill when the user wants a .docx.

After saving the MOP or change control, offer:
> "Want a Word copy (.docx) for the CAB?"

If yes, convert the saved markdown. `<plugin root>` is two levels above this skill's base
directory. No install is needed: it uses python-docx if present, otherwise
`uv run --with python-docx`.
```bash
python3 "<plugin root>/scripts/damira.py" docx documents/<id>/mop.md
```
1. It writes `mop.docx` and `mop.html` next to the markdown. The `.md` stays the source:
   edit it and re-run, never hand-edit the `.docx`.
2. If the Anthropic docx skill is installed, you may use it on `mop.docx` for house
   styling or tracked changes. The file the command wrote is the canonical copy either way.
3. Offer the preview: `mop.html` is self-contained and opens in any browser, including
   the Browser pane.
4. **Optional: share as an artifact.** Only if the Artifact tool is available in this
   session (skip this silently where it isn't), and only if the user says yes. Publishing
   uploads the page, so never publish the unredacted preview:
   ```bash
   python3 "<plugin root>/scripts/damira.py" docx documents/<id>/mop.md \
     --redact --out-dir documents/<id>/share
   ```
   Show the redaction counts it prints, ask the user to confirm
   `documents/<id>/share/mop.html` has nothing sensitive left, then publish that file.
- Exit code 4 means only the `.html` was written: there's no python-docx and no uv.
  Suggest installing uv. `--remote` sends the document to Damira to convert, so **ask
  the user first** before re-running with it.
