# Word copy and preview

Used from Step 6 of the upgrade-plan skill when the user wants a .docx.

After saving the MOP or change control, offer:
> "Want a Word copy (.docx) for the CAB?"

If yes, convert the saved markdown:
```bash
~/.damira/bin/damira docx documents/<id>/mop.md
```
No install is needed: it uses python-docx if present, otherwise `uv run --with python-docx`.

1. It writes `mop.docx` and `mop.html` next to the markdown. The `.md` stays the source:
   edit it and re-run, never hand-edit the `.docx`.
2. If a docx skill is installed in Cursor, you may use it on `mop.docx` for house styling.
   The file the command wrote is the canonical copy either way.
3. Offer the preview: `mop.html` is self-contained. Open it in Cursor's browser.
4. **If this Cursor build can show a canvas**, build one from the `.md` (sections, tables,
   UNVERIFIED items highlighted). Keep it local. No canvas available? The preview covers
   it. Don't mention the canvas.
- Exit code 4 means only the `.html` was written: there's no python-docx and no uv.
  Suggest installing uv. `--remote` sends the document to Damira to convert, so **ask
  the user first** before re-running with it.
- Before the preview goes anywhere outside this machine, re-run with
  `--redact --out-dir documents/<id>/share` and share only that file.
