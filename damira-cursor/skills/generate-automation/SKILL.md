---
name: generate-automation
description: Write Python network automation — Nornir, Netmiko, or Scrapli scripts with a YAML inventory — then validate it locally before handing it back. Use when the user asks for a Python script, Nornir task, Netmiko or Scrapli code to push config, collect show output, back up configs, or audit a fleet of Cisco, Arista, Juniper, Palo Alto, or Fortinet devices. For Ansible use generate-playbook, for Terraform use generate-terraform, for pyATS/Genie state checks use generate-tests.
---

# Python automation generation (Nornir / Netmiko / Scrapli)

You write the code. Damira supplies the vendor facts and the gate: every script goes
through `damira validate` before you hand it back.

## Step 1: Gather requirements

- **Task** — push config, collect and parse show output, backup, compliance audit
- **Targets** — platforms and OS versions, rough device count
- **Framework** — Nornir for fleets (threaded, inventory-driven); Netmiko or Scrapli for a
  small script. Default to Nornir + nornir_netmiko when the user has no preference.
- **Output** — stdout report, CSV/JSON file, or config pushed to devices

## Step 2: Look up what you are unsure of

Run `~/.damira/bin/damira search-vendor-docs "<query>" --vendor <vendor>` for version-specific CLI you will send, and for the
platform string (`cisco_ios`, `arista_eos`, `juniper_junos`, ...). **If the lookup fails,
say so** rather than sending commands you could not verify.

Read `references/nornir-netmiko-scrapli.md` (beside this file) for the inventory layout,
connection plugins, platform strings and structured-output parsing.

## Step 3: Write the code

- **Inventory** — `automation/inventory/{hosts,groups,defaults}.yaml` (Nornir SimpleInventory)
- **Credentials** — from environment variables only (`os.environ["NET_USERNAME"]`,
  `os.environ["NET_PASSWORD"]`), injected into `defaults` at runtime. Never a password
  literal in code or inventory; if a `password:` value appears in anything you wrote, fix it.
- **Structure** — `main()` with `argparse`; `--dry-run` that prints the commands/diff
  instead of sending; `--limit` to filter hosts
- **Safety** — context managers or `try/finally` for connections; for config pushes, save a
  backup first and use the platform's commit/confirm or compare where it exists
- **Parsing** — TextFSM/Genie via `use_textfsm=True` / `use_genie=True`, not regex on raw CLI
- **Dependencies** — `automation/requirements.txt` with pinned versions

Save under `automation/`.

## Validate loop

**Delegate this loop to the `damira-fixer` subagent** (pinned to a cheap model). Give it the path and `--skill generate-automation`. It runs the command below, fixes only what the findings name, and stops after 3 rounds. Read its report: a change to a device command, module or resource is your call, not its. If the subagent isn't available, run the loop yourself as below.

The validator is `~/.damira/bin/damira validate`. It runs locally (Python AST, `ruff`, YAML lint) and
makes no API call. `--skill` tags the local workflow event with this skill.

```bash
~/.damira/bin/damira validate automation/ --skill generate-automation --host cursor
```

1. Run it on everything you wrote.
2. Fix every FAIL and re-run — at most 3 rounds.
3. Still failing after 3 rounds: stop, tell the user which checks fail and why. Do not hand
   it back as finished.
4. A `skipped` check means the tool is not installed — pass the install hint on; it is not
   a pass. An `UNVERIFIED` result is not a pass either.

## Step 4: Hand back

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r automation/requirements.txt
export NET_USERNAME=... NET_PASSWORD=...     # or source them from your vault
python automation/{script}.py --dry-run --limit <one-host>
```

Lead with the dry run against one device. State what validate reported and any assumption.
