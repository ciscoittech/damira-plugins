# CI pipelines for network automation

Reference pack 1.0 (2026-09-24), condensed from Damira's server skills `pyats-testing` and
`network-automation`.

## Stage order

`lint (damira validate) → syntax → check/plan → manual approval → deploy → post-checks`

Each stage gates the next. Deploy applies exactly what check/plan showed (saved `tfplan`
artifact, same commit). Deploy runs only on the default branch.

## Trust boundary: PR code never reaches the management network

`ansible-playbook --check` is not a sandbox: a task with `check_mode: false`, or
`delegate_to: localhost` plus `ansible.builtin.shell`, still runs. `terraform plan` runs
`data "external"` programs and provider binaries. So whoever can open a PR could run code on
a runner that holds device credentials.

- PR / merge-request jobs (lint, syntax): hosted runners, **no secrets**, no device access.
- check/plan and deploy: only on the default branch (merged, reviewed code), on the
  self-hosted management runner, with credentials scoped to a protected environment.
- Never run a PR-controlled playbook, plan or script on a self-hosted runner.

## damira validate in CI

The validator is a stdlib Python script in the Damira plugin. In CI, vendor a copy of the
plugin's `scripts/` (validate.py, audit_config.py, events.py, damira.py) into the repo, or
check out the plugin, then:

```bash
pip install -r requirements-ci.txt          # exact pins: yamllint, ansible-core, ansible-lint, ruff, jinja2, pyyaml
ansible-galaxy collection install -r collections/requirements.yml   # cisco.ios, arista.eos, ... pinned
DAMIRA_LOG_DIR="$RUNNER_TEMP/damira" python3 scripts/damira.py validate playbooks/
```

The collections are required: ansible-core ships none of `cisco.ios`, `arista.eos`,
`juniper.device`, so `--syntax-check` fails on every fully-qualified module without
them. Exit 1 = a check failed. `UNVERIFIED` exits 0 — install the tools so it cannot happen
in CI.

## GitHub Actions

Pin every action to a full commit SHA (the tag in the comment is for humans); resolve it with
`gh api repos/actions/checkout/commits/v4 --jq .sha` and review before pinning.

```yaml
name: network-deploy
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
concurrency:
  group: network-deploy-${{ github.ref }}
  cancel-in-progress: false               # never cancel a deploy half-way
jobs:
  lint:                                   # PRs too: hosted runner, no secrets
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-commit-sha>        # v4
      - uses: actions/setup-python@<full-commit-sha>    # v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements-ci.txt
      - run: ansible-galaxy collection install -r collections/requirements.yml
      - run: python3 scripts/damira.py validate playbooks/
  syntax:                                 # PRs too: hosted runner, no secrets
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-commit-sha>        # v4
      - uses: actions/setup-python@<full-commit-sha>    # v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements-ci.txt
      - run: ansible-galaxy collection install -r collections/requirements.yml
      - run: ansible-playbook -i inventory playbooks/site.yml --syntax-check
  check:                                  # merged code only, on the management runner
    needs: syntax
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    environment: production-check         # holds the device credentials
    runs-on: [self-hosted, mgmt]
    steps:
      - uses: actions/checkout@<full-commit-sha>        # v4
      - run: pip install -r requirements-ci.txt && ansible-galaxy collection install -r collections/requirements.yml
      - run: ansible-playbook -i inventory playbooks/site.yml --check --diff
        env:
          NET_USERNAME: ${{ secrets.NET_USERNAME }}
          NET_PASSWORD: ${{ secrets.NET_PASSWORD }}
  deploy:
    needs: check
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    environment: production               # Required reviewers = the approval gate
    runs-on: [self-hosted, mgmt]
    steps:
      - uses: actions/checkout@<full-commit-sha>        # v4
      - run: pip install -r requirements-ci.txt && ansible-galaxy collection install -r collections/requirements.yml
      - run: ansible-playbook -i inventory playbooks/site.yml
        env:
          NET_USERNAME: ${{ secrets.NET_USERNAME }}
          NET_PASSWORD: ${{ secrets.NET_PASSWORD }}
```

Approval: Settings → Environments → `production` → Required reviewers, and restrict both
environments to the `main` branch (Deployment branches). Put the device secrets on the
environments, not the repository, so no PR job can read them. Terraform: `plan -out=tfplan`
in check, `actions/upload-artifact` it, download + `apply tfplan` in deploy.

## GitLab CI

```yaml
stages: [lint, syntax, check, deploy]
default:
  image: python:3.12.7-slim               # pin the tag (or digest)
.tools: &tools
  - pip install -r requirements-ci.txt
  - ansible-galaxy collection install -r collections/requirements.yml
lint:                                     # MRs too: shared runner, no protected variables
  stage: lint
  script:
    - *tools
    - python3 scripts/damira.py validate playbooks/
syntax:
  stage: syntax
  script:
    - *tools
    - ansible-playbook -i inventory playbooks/site.yml --syntax-check
check:                                    # default branch only, on the management runner
  stage: check
  tags: [mgmt]
  script:
    - *tools
    - ansible-playbook -i inventory playbooks/site.yml --check --diff
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
deploy:                                   # the approval gate IS this job: manual + protected env
  stage: deploy
  tags: [mgmt]
  resource_group: production              # one deploy at a time
  environment: {name: production}
  allow_failure: false                    # pipeline stays blocked until someone runs it
  script:
    - *tools
    - ansible-playbook -i inventory playbooks/site.yml
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual                        # inside the rule: works on every GitLab version
```

Protect the `production` environment (Settings → CI/CD → Protected environments → Allowed
to deploy: the approvers). GitLab enforces that on the job that has `environment:`, so the
manual gate must be on `deploy` itself. Never gate with a separate manual `approve` job and
an automatic `deploy`: anyone who can play `approve` then triggers `deploy`, which runs as
the pipeline user and skips the check. For a second pair of eyes add Deployment approvals
on the protected environment (Premium). Device credentials are masked **protected** variables (only
protected branches see them), and the `mgmt` runner is registered as protected so MR
pipelines can never be scheduled on it.

## Rules

- Secrets only from the CI secret store, scoped to protected environments/branches; never
  echo them; never in the YAML.
- PR/MR jobs run on hosted runners without secrets; check/plan/deploy only on the default
  branch on the management runner.
- Pin actions by commit SHA, images by tag or digest, pip packages with `==` in
  `requirements-ci.txt`, collections with versions in `collections/requirements.yml`.
- `resource_group` (GitLab) / `concurrency` (GitHub) so two deploys never overlap.
- Post-deploy: pyATS post-snapshot + diff (see generate-tests) and fail loudly.
