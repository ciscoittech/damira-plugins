# Hand-off: Terraform

Terraform changes go through a plan the engineer reviews and an apply they run, usually
from their pipeline. Damira generates and validates the HCL; it never runs or applies it.

## What the Terraform MCP server is for

The `~~iac` server is used for documentation only:

- provider and resource lookups: arguments, required versions, deprecations
- module lookups: inputs, outputs, examples
- policy lookups, if the engineer uses them

Its workspace and run tools (create a run, apply, discard, change a workspace) are blocked
by the device gate in advisor mode. Don't look for another route to them.

## Flow

1. generate-terraform writes the configuration, using the source-of-truth objects as
   variables or data sources.
2. `damira validate` (Step 3) runs fmt, init without a backend, and validate.
3. The engineer runs the plan, locally or in CI:

```bash
terraform -chdir=terraform/<name> init
terraform -chdir=terraform/<name> plan -out tfplan
terraform -chdir=terraform/<name> show -no-color tfplan > notes/tfplan.txt
```

4. Summarise the saved plan for the report: adds, changes and destroys per resource, and
   any destroy called out first.
5. The engineer applies from their pipeline after review.

## NetBox as input, not output

The NetBox Terraform provider can read NetBox as data sources. Only manage NetBox objects
as Terraform resources if the engineer's NetBox is already managed that way; otherwise a
plan would try to take ownership of records people edit by hand.

## No Terraform server detected

Nothing changes except the lookups: use the generator's vendor documentation lookup
instead, and the flow above stays the same.
