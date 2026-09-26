---
name: generate-terraform
description: Write Terraform for network infrastructure — NetBox, Palo Alto PAN-OS, FortiOS, Cisco Meraki, Cisco IOS-XE and NX-OS providers — then validate it locally and end with terraform plan. Use when the user asks for Terraform, HCL, or infrastructure-as-code for firewall rules and objects, NetBox IPAM/DCIM records, Meraki networks and SSIDs, VLANs, or interfaces. Arista EOS/CloudVision has no Terraform provider — use generate-playbook. For Ansible use generate-playbook, for Python use generate-automation, for a CI pipeline around it use generate-pipeline.
---

# Terraform generation

You write the HCL. Damira supplies the vendor facts and the gate: every configuration goes
through `damira validate` (fmt + init + validate) before you hand it back, and the hand-back
is always `terraform plan`, never `apply`.

## Step 1: Gather requirements

- **Target** — which system (NetBox, PAN-OS/Panorama, FortiGate, Meraki, IOS-XE, NX-OS; Arista EOS/CloudVision routes to generate-playbook)
- **Resources** — rules, objects, VLANs, prefixes, SSIDs, interfaces
- **State** — local for a trial; a remote backend with locking for anything shared
- **Existing objects** — anything already on the device needs `import` blocks, not re-creation

## Step 2: Look up the provider

Read `references/terraform-providers.md` (beside this file) for the provider source, a
version-constraint pattern, auth env vars and known quirks. Run
`~/.damira/bin/damira search-vendor-docs "<query>" --vendor <vendor>` for resource names and arguments you are not sure of —
providers rename resources between major versions. **If the lookup fails, say so**
rather than emitting arguments you could not verify.

## Step 3: Write the configuration

Save under `terraform/{name}/`:

- `versions.tf` — `required_version` and `required_providers` with `~>` pins
- `providers.tf` — provider blocks with **no credentials**; auth comes from the provider's
  env vars (listed in the reference pack) or `sensitive = true` variables
- `variables.tf` — typed variables with `validation` blocks where values are constrained
- `main.tf` — resources; `for_each` over maps (stable keys), not `count`
- `outputs.tf` — what the user needs to see after plan/apply
- `terraform.tfvars.example` — example values, no secrets

Run `terraform fmt` yourself if it is installed; validate fails on unformatted files.

**Sources:** providers only from the registry namespaces listed in
`references/terraform-providers.md`; modules only from the Terraform Registry or local
paths. No `git::`, `http(s)://`, `s3::` or other remote module sources, and no
`data "external"`, unless the user asked for that exact source.

## Validate loop

**Delegate this loop to the `damira-fixer` subagent** (pinned to a cheap model). Give it the path and `--skill generate-terraform`. It runs the command below, fixes only what the findings name, and stops after 3 rounds. Read its report: a change to a device command, module or resource is your call, not its. If the subagent isn't available, run the loop yourself as below.

The validator is `~/.damira/bin/damira validate`. It runs `terraform fmt -check`, then `init
-backend=false` + `validate` on a throwaway copy (nothing is left in the user's folder). It
makes no Damira API call; `init` does download the providers you named. `--skill` tags the
local workflow event with this skill.

```bash
~/.damira/bin/damira validate terraform/{name}/ --skill generate-terraform --host cursor
```

0. **Ask before the first run.** `init` downloads every provider and module you named and
   runs provider binaries on the user's machine. The post-write hook does not run on
   `terraform/` at all (it watches `configs/`, `automation/`, `playbooks/` only), so this
   explicit loop is the only check. List the `required_providers` sources/versions and any module
   `source` for the user and run validate only after they approve. Anything outside the
   pack's namespaces needs their explicit yes.
1. Run it on the directory you wrote.
2. Fix every FAIL and re-run — at most 3 rounds.
3. Still failing after 3 rounds: stop, tell the user which checks fail and why. Do not hand
   it back as finished.
4. A `skipped` check means terraform is not installed — pass the install hint on; it is not
   a pass. An `UNVERIFIED` result is not a pass either.

## Step 4: Hand back — end with plan

```bash
cd terraform/{name}
export <PROVIDER_AUTH_ENV_VARS>          # see references/terraform-providers.md
terraform init
terraform plan -out=tfplan               # review every change before anything else
```

Do not tell the user to run `apply` until they have reviewed the plan. State what validate
reported and any assumption.
