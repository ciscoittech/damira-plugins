---
name: generate-pipeline
description: Write a CI/CD pipeline for network automation — GitHub Actions or GitLab CI with lint (damira validate), syntax, check-mode or plan, a manual approval gate, then deploy — and validate it locally. Use when the user asks for a pipeline, CI, GitOps, GitHub Actions workflow, or .gitlab-ci.yml around Ansible playbooks, Terraform, Nornir scripts or configs. For the automation itself use generate-playbook, generate-terraform or generate-automation; for pre/post checks use generate-tests.
allowed-tools: mcp__plugin_damira_damira__damira_search_vendor_docs, mcp__damira__damira_search_vendor_docs
---

# CI pipeline generation (GitHub Actions / GitLab CI)

You write the pipeline. Damira supplies the gate: the pipeline's first stage runs
`damira validate`, and the pipeline file itself goes through `damira validate` before you
hand it back.

## Step 1: Gather requirements

- **Platform** — GitHub Actions or GitLab CI
- **What it deploys** — Ansible (`playbooks/`), Terraform (`terraform/`), Python (`automation/`)
- **Runners** — deploy jobs need a runner that can reach the devices (self-hosted, in the
  management network). Lint/syntax jobs — the only ones that run on PRs — must run on
  hosted runners with no secrets.
- **Approval** — who approves production (GitHub Environment reviewers / GitLab protected
  environment + `when: manual` on the deploy job itself)

## Step 2: Read the reference

Read `references/ci-pipelines.md` (beside this file) for the stage layout, approval-gate
syntax on both platforms, and how to install `damira validate` in CI.

## Step 3: Write the pipeline

Stages, in this order — each gates the next:

1. **lint** — `damira validate <dir>` (fails the pipeline on any FAIL); install the pinned
   tools and `ansible-galaxy collection install -r collections/requirements.yml` first
2. **syntax** — `ansible-playbook --syntax-check` / `terraform validate` / `python -m py_compile`
3. **check** — `ansible-playbook --check --diff` or `terraform plan -out=tfplan` (save the
   plan as an artifact); pyATS pre-change snapshot if tests exist. **Default branch only**:
   check mode and plan still execute code from the repo, so they never run on PR code
4. **approve** — manual approval gate on the deploy job itself (GitHub: the job's
   `environment:` with required reviewers; GitLab: `when: manual` on the job that has
   `environment: production`). Never a separate manual job in front of an automatic deploy —
   that gate is bypassable. Production only, never skipped on the default branch
5. **deploy** — apply exactly what was checked (`terraform apply tfplan`), then post-change tests

Rules: lint and syntax run on PRs on hosted runners with **no secrets**; check, approve and
deploy run only on the default branch on the management runner. Never run a PR-controlled
playbook, plan or script on a self-hosted runner. Secrets only from the CI secret store,
scoped to a protected environment (`${{ secrets.X }}` on an Environment / masked protected
GitLab variables), never in the file. Pin actions by commit SHA, images by tag, pip and
collection versions exactly. Add `concurrency` / `resource_group`.

Save as `.github/workflows/network-deploy.yml` or `.gitlab-ci.yml`.

## Validate loop

**Delegate this loop to the `damira:damira-fixer` agent** (it runs on Haiku). Give it the path, `--skill generate-pipeline`, and `<plugin root>`. It runs the command below, fixes only what the findings name, and stops after 3 rounds. Read its report: a change to a device command, module or resource is your call, not its. If the agent isn't available, run the loop yourself as below.

The validator ships in this plugin, two levels above this skill's base directory:
`<plugin root>/scripts/damira.py`. It runs locally (yamllint) and makes no API call.
`--skill` tags the local workflow event with this skill.

```bash
python3 "<plugin root>/scripts/damira.py" validate .github/workflows/network-deploy.yml --skill generate-pipeline --host claude-code
```

(or `.gitlab-ci.yml`). Then validate what the pipeline deploys, so its lint stage will pass.

1. Run it on everything you wrote.
2. Fix every FAIL and re-run — at most 3 rounds.
3. Still failing after 3 rounds: stop, tell the user which checks fail and why. Do not hand
   it back as finished.
4. A `skipped` check means the tool is not installed — pass the install hint on; it is not
   a pass. An `UNVERIFIED` result is not a pass either.

## Step 4: Hand back

Tell the user which secrets/variables to create, which runner the deploy stage needs, and
how to configure the approvers (GitHub: Settings → Environments → production → Required
reviewers; GitLab: Settings → CI/CD → Protected environments). Recommend a first run on a
branch that stops at the approval gate. State what validate reported and any assumption.
