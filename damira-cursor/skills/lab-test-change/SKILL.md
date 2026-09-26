---
name: lab-test-change
description: Test a network change in a throwaway ContainerLab lab before it goes near production — deploy the lab, apply the playbook or script, run show-command or pyATS/Genie checks, report pass/fail, and always destroy the lab. Use when the user says "test this in a lab first", "prove this change before the window", "dry-run this playbook against a lab", or wants evidence a change works before a CAB. Needs docker and containerlab on the engineer's machine; without them it validates only and says so. To only build a lab, use generate-lab; to write the change, use generate-playbook, generate-automation or generate-terraform.
---

# Lab before prod

You drive the flow in the engineer's own shell. Damira supplies the runner and the gate:
`damira lab` deploys, applies, checks, writes the report and **always** runs
`containerlab destroy --cleanup`, even when the apply or a check fails.

The runner is `~/.damira/bin/damira lab`. It runs locally and makes no API call.

**Never point this at production.** The apply step targets the lab's own inventory
(`clab-<lab>/ansible-inventory.yml`). If the user's playbook hard-codes production hosts,
stop and say so.

## Step 1: Gather what is being tested

- **The change** — an existing playbook/script path, or what to generate
- **Platforms** — what production runs, so the lab can stand in for it
- **Pass criteria** — what must be true after (neighbor Established, route present, NTP
  servers configured) and what must NOT change

## Step 2: Preflight

```bash
~/.damira/bin/damira lab preflight
```

`"mode": "lab"` means docker, the daemon and containerlab are all present. `"mode":
"validate-only"` means something is missing (`reason` says what). **Tell the user now**
that the run will only validate, not test, and pass on the reason. Continue anyway: a
validated topology, change and checks file is still worth handing back.

## Step 3: Build or reuse the lab

If `labs/<lab>.clab.yml` already exists, reuse it. Otherwise follow the `generate-lab`
skill to write a small topology that mirrors the slice of production the change touches.
Free kinds stand in for licensed ones (FRR for IOS-XE routing, SR Linux for a DC fabric);
note the fidelity gap in the report. Then:

```bash
~/.damira/bin/damira lab validate labs/<lab>.clab.yml
```

Fix every error it names and re-run until `"ok": true`.

## Step 4: Get the change

If the user has no change yet, follow `generate-playbook` (Ansible), `generate-automation`
(Nornir/Netmiko/Scrapli) or `generate-terraform`. Those skills run their own `damira
validate` loop. Target the lab inventory. Do not hand-write device commands here.

## Step 5: Write the checks

Write `labs/<lab>.checks.json`: one entry per pass criterion, in the eval harness
`StateCheck` shape. Read `references/lab-checks.md` (beside this file) for the fields,
matcher semantics and examples. `{lab}` in a command expands to the lab name, so
`docker exec clab-{lab}-r1 vtysh -c 'show bgp summary json'` reaches node `r1`.

For a pyATS/Genie learn→diff, follow `generate-tests` for the testbed and job, pass the
pre-change snapshot as `--before`, and add the post-change diff as a command check
(details in the reference).

## Step 6: Run it

```bash
~/.damira/bin/damira lab run labs/<lab>.clab.yml \
  --apply playbooks/<change>.yml --checks labs/<lab>.checks.json
```

Add `--sudo` if containerlab needs root on this machine, `--before "<cmd>"` for a
pre-change snapshot, `--inventory <file>` for a non-default inventory. Run it in the
foreground and let it finish: it tears the lab down itself. If the run is killed hard,
run `sudo containerlab destroy -t labs/<lab>.clab.yml --cleanup` before anything else.

Exit 0 is `pass` or `validate-only`; exit 1 is any failure.

## Step 7: Present the report

Read `lab-reports/<lab>-lab-report.md` (the `.json` beside it has the raw output) and give
the user:

1. The headline: PASS, FAIL, or **VALIDATE-ONLY — NOT lab-tested**
2. The per-check table, and for each failure the observed output that broke it
3. Teardown status. If it says FAILED, give the destroy command above
4. Fidelity caveats: which lab kinds stood in for which production platforms

A FAIL is a finding, not a bug in the runner: offer the `troubleshoot` skill with the
failing check's output. Never describe a validate-only run as tested.
