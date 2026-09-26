---
name: generate-tests
description: Write network tests — pyATS/Genie learn, change, learn, diff jobs that prove a change did what it should and nothing else, and pytest tests for automation scripts — then validate them locally. Use when the user asks for pyATS, Genie, AEtest, a testbed file, pre/post change verification, state snapshots, or unit tests for a Nornir/Netmiko script. For the change itself use generate-playbook, generate-automation or generate-terraform.
---

# Test generation (pyATS / Genie / pytest)

You write the tests. Damira supplies the vendor facts and the gate: every test file goes
through `damira validate` before you hand it back.

## Step 1: Gather requirements

- **What changed** — the feature the change touches (bgp, ospf, interface, vlan, routing, ...)
- **Devices** — platforms (Genie `os`: `iosxe`, `nxos`, `eos`, `junos`, ...) and how to reach them
- **Pass criteria** — what must be true after (neighbors Established, route present, VLAN
  on trunk) and what must NOT change
- **Kind** — device-state test (pyATS) or unit test for a script (pytest)

## Step 2: Look up parsers and features

Read `references/pyats-genie.md` (beside this file) for the testbed layout, learn/diff
pattern and AEtest structure. Run `~/.damira/bin/damira search-vendor-docs "<query>" --vendor <vendor>` when you need a parser or
`learn()` feature for a platform you are not sure Genie supports. **If the lookup fails,
say so** rather than calling a parser that may not exist.

## Step 3: Write the tests

**pyATS — learn → change → learn → diff** (save under `tests/network/`):

- `testbed.yml` — credentials as `"%ENV{NET_USERNAME}"` / `"%ENV{NET_PASSWORD}"`, never literals
- `snapshot.py` — `device.learn(<feature>)` for each feature, saved to `snapshots/pre/` or `post/`
- `test_change.py` — AEtest: CommonSetup connects; one Testcase per pass criterion using
  `device.parse()`; a diff Testcase comparing pre/post with `genie.utils.diff.Diff` and
  failing on changes outside the expected set; CommonCleanup disconnects
- `job.py` — easypy job that runs `test_change.py`

**pytest — for scripts** (save under `tests/`): mock the connection (Netmiko
`ConnectHandler`, Nornir task results) and test parsing, filtering and dry-run output.
Never open a real device connection from a unit test.

## Validate loop

**Delegate this loop to the `damira-fixer` subagent** (pinned to a cheap model). Give it the path and `--skill generate-tests`. It runs the command below, fixes only what the findings name, and stops after 3 rounds. Read its report: a change to a device command, module or resource is your call, not its. If the subagent isn't available, run the loop yourself as below.

The validator is `~/.damira/bin/damira validate`. It runs locally (Python AST, `ruff`, YAML lint) and
makes no API call. `--skill` tags the local workflow event with this skill.

```bash
~/.damira/bin/damira validate tests/ --skill generate-tests --host cursor
```

1. Run it on everything you wrote.
2. Fix every FAIL and re-run — at most 3 rounds.
3. Still failing after 3 rounds: stop, tell the user which checks fail and why. Do not hand
   it back as finished.
4. A `skipped` check means the tool is not installed — pass the install hint on; it is not
   a pass. An `UNVERIFIED` result is not a pass either.

## Step 4: Hand back

```bash
pip install "pyats[library]"
python tests/network/snapshot.py --testbed tests/network/testbed.yml --phase pre
# ... make the change ...
python tests/network/snapshot.py --testbed tests/network/testbed.yml --phase post
pyats run job tests/network/job.py --testbed-file tests/network/testbed.yml
```

For pytest: `pytest tests/ -q`. State what validate reported and any assumption.
