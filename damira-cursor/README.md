# Damira — Cursor plugin

CCIE-level network operations inside Cursor: troubleshooting, upgrade planning, config
audit, device configuration, validated automation (Ansible, Python, Terraform, pyATS,
CI pipelines), Word and Excel deliverables, topology diagrams, and ContainerLab topologies.

**No PyPI package. No uvx. No pip. No Python toolchain.** Two ways to use it, both
dependency-free:

| Path | What you get | Setup |
|---|---|---|
| **Skills** (default) | 13 skills invoking bundled scripts | load the plugin |
| **MCP** (optional) | the same 7 tools as MCP, for Cursor / Claude Code / Claude Desktop / Windsurf | `damira install-mcp` |

The MCP server is hand-rolled over stdio in the standard library, so adding it costs no
dependencies. `damira-mcp` on PyPI is **not** required and is not used.

Issues: [github.com/ciscoittech/damira-plugins/issues](https://github.com/ciscoittech/damira-plugins/issues).

## What's new in 0.3.0

- **Validated automation.** The playbook, automation, Terraform, test and pipeline generators run `damira validate` on what they write and fix it (up to 3 rounds) before handing it back.
- **Word and Excel deliverables.** MOPs and change controls export to `.docx`, and procedure workbooks to `.xlsx`, each with an HTML preview. Nothing to install: the scripts use python-docx or openpyxl if present, otherwise `uv run --with`.
- **Topology diagrams.** `damira diagram build` reads `configs/` plus CDP/LLDP output; `damira diagram render` draws it. `--redact` writes a copy with hostnames and addresses replaced, for sharing.
- **Cheaper runs.** Mechanical steps (rendering, fixing validation findings) are handed to small agents that run on a cheap model, so premium models are kept for diagnosis.
- **Golden configs.** `damira render` produces NTP, AAA/TACACS+, SNMPv3, syslog and banner baselines for IOS, NX-OS, EOS and Junos.
- **Opt-in usage stats.** `damira stats` shows your local workflow history. Uploading anonymised counts to Damira is off unless you set `DAMIRA_TELEMETRY=1`; no config text, file names or hostnames are ever sent.

## Install

### Local (development)

```bash
agent --plugin-dir /path/to/plugins/damira-cursor
```

Or symlink it for the IDE:

```bash
ln -s /path/to/plugins/damira-cursor ~/.cursor/plugins/local/damira
# then: Developer: Reload Window
```

### API key

The scripts read `DAMIRA_API_KEY` from **your shell environment**. Add it to your profile:

```bash
export DAMIRA_API_KEY='oncall_sk_...'      # ~/.zshrc or ~/.bashrc
```

Or write it to `~/.damira/config`:

```
DAMIRA_API_KEY = oncall_sk_...
```

Without a key it falls back to a shared demo key (50 queries/day) so you can try it first,
and every answer on it starts with a note saying so. Get your own at
https://damiraai.com/dashboard/api-keys. `DAMIRA_API_KEY` wins over `~/.damira/config`.
Restart Cursor after exporting, then check with `~/.damira/bin/damira whoami`, which prints
the masked key and where it came from.

Full guide: [damiraai.com/docs/install#api-key](https://damiraai.com/docs/install#api-key).

> **Why not the plugin's `variables` prompt?** Cursor's `variables` values do reach
> `mcp.json` and hook configs, but **not** the agent's shell — verified 2026-08-08 — and
> the shell is where these scripts run. Env returned from a `sessionStart` hook has the
> same limitation. The parent process environment is the only path that works, so the
> `export` is real and this README will not pretend otherwise.

Verify:

```bash
~/.damira/bin/damira whoami
```

## Setting up a project

Ask the agent to "set up a Damira workspace" (the `damira-init` skill), or run
it yourself:

```bash
~/.damira/bin/damira init --vendor Cisco --platform "Core: Catalyst 9300, IOS-XE 17.9.4"
```

It creates `configs/` (git-ignored), `documents/` and `notes/`, and writes a
marked Damira block with your network details into `AGENTS.md`. Re-running
replaces only that block.

## The device gate

In advisor mode Damira's own device tools are denied outright. A shell
`ssh`/`telnet`/`nc` is handed to you to approve instead of being blocked —
engineers reach servers and jump hosts the same way they reach network gear, and
a blanket block breaks ordinary terminal work. Set `DAMIRA_DEVICE_GATE=strict` to
block those too.

## MCP (optional)

```bash
~/.damira/bin/damira install-mcp                     # Cursor
~/.damira/bin/damira install-mcp --target all        # + Claude Desktop
agent mcp enable damira                              # Cursor requires approval
agent mcp list-tools damira                          # → 7 tools
```

`install-mcp` **merges** into `~/.cursor/mcp.json` and
`~/Library/Application Support/Claude/claude_desktop_config.json` rather than overwriting —
those files usually hold other people's servers. It refuses to clobber an existing `damira`
entry without `--force`, and it does not write your API key into the file; the server
resolves the key at run time.

Tools: `damira_search_vendor_docs`, `damira_search_cve`, `damira_search_release_notes`,
`damira_troubleshoot`, `damira_upgrade_plan`, `damira_agent`, `analyze_config`.

> **Plugin-bundled `mcp.json` does not work in the Cursor CLI.** Verified 2026-08-08:
> a plugin's own `mcp.json` is not loaded via `--plugin-dir`, with an explicit
> `mcpServers` manifest field, or installed under `~/.cursor/plugins/local`. Only project
> `.cursor/mcp.json` and user `~/.cursor/mcp.json` are read. That is why `install-mcp`
> exists rather than the plugin just shipping the config. The bundled `mcp.json` is kept
> for the IDE, where it is documented to work, but it is untested there.

MCP tool errors set `isError`, which is the same "this is not an answer" contract the CLI
expresses as a non-zero exit. Both surfaces share one implementation — `mcp/server.py`
imports `scripts/damira.py` rather than duplicating the API logic.

## How it works

On session start, a hook writes two shims:

```
~/.damira/bin/damira                 → scripts/damira.py
~/.damira/bin/damira-audit-config    → scripts/audit_config.py
```

They are rewritten every session, so plugin updates and moves are picked up with nothing
to reinstall. Skills invoke those stable paths — `CURSOR_PLUGIN_ROOT` is set for hooks but
is **not** visible to the agent's shell, so a skill cannot reference it.

| Component | What it does |
|---|---|
| `scripts/damira.py` | 6 subcommands → `POST /api/extension/agent/chat-sync`. Stdlib only. |
| `scripts/audit_config.py` | Regex config audit. **Runs locally — config text never leaves the machine.** |
| `rules/damira.mdc` | Always-on: division of labour, when to call, error contract, advisor posture |
| `hooks-handlers/device_gate.py` | `beforeShellExecution` — asks before SSH/telnet in advisor mode (`strict` blocks), fail-closed |
| `hooks-handlers/session_start.py` | Installs shims, warns on missing key, exports execution mode |
| `skills/` (13) | troubleshoot, upgrade-plan, config-audit, generate-config, generate-lab, damira-init, and the generators generate-playbook, generate-automation, generate-terraform, generate-tests, generate-pipeline, generate-workbook, generate-diagram |
| `agents/` | damira-renderer and damira-fixer: small agents for the mechanical steps, so they can run on a cheap model |

## The error contract

**A non-zero exit means the result is NOT an answer.** The scripts exit non-zero on
transport failures, auth failures, rate limits, and on refusals the service returns
*inside* a 200 body.

That last case is the important one. A tier refusal returned as a normal response once
produced a fabricated 371-line upgrade MOP that reported itself as successful — an
engineer would have executed it against production. The client-side refusal check
(`REFUSAL_MARKERS` in `damira.py`) is a stopgap until the gateway returns proper 4xx
status codes (#358 Phase 1). **Do not remove it before that lands.**

## Verified behaviour

Measured 2026-08-08 against `agent` v2026.08.04-aaa8809:

- plugin-bundled `hooks/hooks.json` loads via `--plugin-dir`
- the device gate **denies SSH even under `--force`/`--yolo`**, and the agent falls back
  to presenting commands for the engineer to run
- `config-audit` fires on natural phrasing ("review this config and tell me how bad it
  is") with no skill or tool name mentioned
- `damira.py` correctly gates a live tier refusal to a non-zero exit instead of passing
  it through as data
- `audit_config.py` matches the original `analyze_config` output

## What does not port from the Claude Code package

**The document evidence gate.** In Claude Code it is a `PreToolUse` hook on `Write|Edit`.
Cursor has `beforeReadFile` and `afterFileEdit` but **no `beforeFileEdit`**, so there is
no point at which to block a fabricated document *before* it is written. Anti-fabrication
here rests on the script exit codes plus the skill-level evidence gates in
`upgrade-plan/SKILL.md`. That is one layer weaker than the Claude Code story, and it is
worth saying plainly rather than claiming parity.

**`allowed-tools` pre-approval.** No Cursor equivalent. The analogue is `.cursor/cli.json`
permission rules, which are user-owned and cannot be shipped by a plugin — Cursor's plugin
manifest has no `permissions` field.

## Known issues

- `variables` interpolation is unverified under a real marketplace install — `--plugin-dir`
  has no UI to supply values, so the test could not distinguish "unsupported" from "no
  value available" (#358 Task 0.4).
- Marketplace listing requires the package to be open source, which is gated on **#354**.

## Local test

```bash
~/.damira/bin/damira whoami
~/.damira/bin/damira --help
printf 'hostname r1\nenable password x\n' | ~/.damira/bin/damira-audit-config -
echo '{"command":"ssh admin@10.0.0.1"}' | python3 hooks-handlers/device_gate.py   # → ask
```
