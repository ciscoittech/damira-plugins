# Lab checks

Reference for `labs/<lab>.checks.json`, read by `damira lab run --checks`.

## Format

A JSON list of checks (or `{"checks": [...]}`). Each check is an eval-harness `StateCheck`
(`services/oncall-agent/labs/harness/schema.py` in the Damira repo), so a check that
passes here means the same thing as a check in Damira's own executed evals. Unknown
fields are rejected, so a typo cannot silently skip a check.

| Field | Meaning |
|---|---|
| `command` | Shell command run on the engineer's machine. `{lab}` expands to the lab name |
| `output` | `true`: match the apply step's stdout instead of running a command |
| `regex` | Passes if the pattern is found (multiline search) |
| `contains` | Passes if the text appears in the output |
| `equals` | Passes if the whole output equals this (trailing newline counts: prefer `regex: "^2$"`) |
| `exists` | `true` (default): output is non-empty. `false`: output must be empty |
| `wait_s` | Keep retrying for this many seconds (sessions take time to come up) |

A `command` check passes only when the command exits 0 **and** the matcher (if any)
matches. A `command` with no matcher passes on exit 0 alone. Matchers are checked in the
order `regex`, `equals`, `contains`, `exists`; give one per check.

`node` + `path` (SR Linux JSON-RPC gets) exist in the harness but are not run by the
plugin: write them as a `command` (`docker exec clab-{lab}-leaf1 sr_cli -- info ...`).

## Examples

Every node in a deployed lab is a container named `clab-<lab>-<node>`.

```json
[
  {"output": true, "regex": "failed=0"},
  {"command": "docker exec clab-{lab}-r1 vtysh -c 'show bgp summary json'",
   "regex": "\"state\":\\s*\"Established\"", "wait_s": 60},
  {"command": "docker exec clab-{lab}-r1 vtysh -c 'show ip route 10.2.2.2/32'",
   "contains": "10.2.2.2/32", "wait_s": 30},
  {"command": "docker exec clab-{lab}-r1 vtysh -c 'show running-config' | grep -c '^ntp server'",
   "regex": "^2$"}
]
```

- Ansible: `{"output": true, "regex": "failed=0"}` catches a play that exits 0 with an
  ignored failure.
- Use JSON show output (`| json`, `show ... json`) where the platform has it: a regex on
  a JSON key is steadier than one on a column layout.
- A check that must NOT change is a check too: `grep -c` the protected line and match
  the count it had before.

Per-platform CLI entry points: FRR `vtysh -c`, SR Linux `sr_cli --`, cEOS `Cli -p 15 -c`,
cRPD `cli -c`, VyOS `/opt/vyatta/bin/vyatta-op-cmd-wrapper`.

## pyATS / Genie learn → diff

`generate-tests` writes the testbed, `snapshot.py` and the job. In a lab:

1. **Testbed** — point each device at its lab management address from
   `containerlab inspect -t labs/<lab>.clab.yml --format json`, with the lab image's
   default credentials passed as `%ENV{NET_USERNAME}` / `%ENV{NET_PASSWORD}`.
2. **Pre snapshot** — pass it as `--before`, which runs after deploy and before apply:
   `--before "python tests/network/snapshot.py --testbed tests/network/lab-testbed.yml --phase pre"`
3. **Post snapshot + diff** — add one command check that takes the post snapshot and
   diffs. It must **exit non-zero on an unexpected change** (the check passes on exit 0):

```json
{"command": "python tests/network/snapshot.py --testbed tests/network/lab-testbed.yml --phase post && python tests/network/diff.py snapshots/pre snapshots/post"}
```

`diff.py` compares with `genie.utils.diff.Diff`, excludes the expected-change keys and
volatile ones (`up_time`, `last_reset`, counters), prints the diff and calls
`sys.exit(1)` if anything is left. An AEtest job (`pyats run job ...`) works as a check
the same way, as long as its exit code reflects the result.

## Report

`lab-reports/<lab>-lab-report.json` and `.md` beside the topology (or `--out-dir`):
result (`pass`, `fail`, `apply-failed`, `deploy-failed`, `before-failed`, `error`,
`invalid`, `validate-only`), mode, preflight reason, topology errors, deploy/before/apply
output tails, one row per check with the observed output, and teardown status.

## Why the lab runs on the engineer's machine

The lab, the apply and the checks all run locally: device configs never leave the
machine and the run costs nothing. Damira ships the runner and the check semantics.
