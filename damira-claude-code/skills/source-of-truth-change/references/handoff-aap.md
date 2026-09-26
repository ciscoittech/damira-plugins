# Hand-off: Ansible Automation Platform in check mode

The engineer's AAP (or AWX) runs the playbook. Damira never runs it for real: this skill
launches in check mode so the engineer sees a diff, and the live run is theirs.

## Before launching

1. **The playbook must be in the project AAP syncs.** AAP runs playbooks from a project
   (a Git repo), not from local files. The engineer commits the validated playbook to a
   branch of that repo. If the project allows branch override and the template prompts for
   it, pass that branch on launch; otherwise the engineer merges or syncs first.
2. **Find the job template** with the `~~automation` server's lookup tools: by name, or by
   the playbook it runs. Read its settings before launching.
3. **Check the template prompts on launch.** AAP ignores a launch field unless the
   template asks for it, and reports it as ignored. A launch with `job_type=check` on a
   template that doesn't prompt for job type runs the template's own type, which may be
   `run`. So:
   - job type prompt on (`ask_job_type_on_launch`): required. If off, do not launch;
     tell the engineer to enable the prompt or launch it in check mode themselves.
   - diff mode prompt (`ask_diff_mode_on_launch`): wanted, so the output shows the lines.
   - limit prompt (`ask_limit_on_launch`): wanted, to start with one host.

## Launch

Launch the template with:

- `job_type`: `check`
- `diff_mode`: `true`
- `limit`: one host first, then the group once the engineer has read the first diff
- `scm_branch`: the branch from step 1, if prompted

The device gate asks the engineer before every launch, because it can't see whether the
template prompts for job type. Tell them you confirmed the prompt so they can approve. Only
the top-level `job_type` counts: one inside `extra_vars` is a playbook variable and the job
runs live. A launch that isn't check mode, or a workflow launch, is blocked in strict mode. Never try to get
around that; a live run is the engineer's decision.

If the launch response lists ignored fields and `job_type` is among them, the job is
running in the template's own mode. Tell the engineer at once so they can cancel it.

## Read the result

Wait for the job to finish, then read its events or output:

- `changed` tasks per host: what the change would do
- the diff lines: the actual config difference
- `failed` or `unreachable` hosts: report them; don't retry in a loop

Check-mode limits to state in the report:

- `*_config` modules with `lines:` report changed when the lines differ from the running
  config, but they can't show what the device would render from them.
- Modules without check-mode support are skipped, so their tasks show nothing.
- Tasks that depend on a previous task's registered result may behave differently in a
  real run.

## The live run

Give the engineer the template, the limit and the branch, and suggest one host first. They
launch it in AAP or approve it when asked. Afterwards, the pyATS hand-off (if detected)
takes the post-change snapshot.

## No AAP detected

Hand back the equivalent CLI instead:

```bash
ansible-playbook -i <inventory> <playbook> --check --diff --limit <one-host>
```
