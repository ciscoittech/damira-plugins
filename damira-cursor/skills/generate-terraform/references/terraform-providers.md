# Terraform providers for network infrastructure

Reference pack 1.1 (2026-09-24), condensed from Damira's server skill `terraform-iac`.
Sources and major versions checked against registry.terraform.io on 2026-09-24.
Provider resources are renamed between majors — check the registry page for the version you
pin, and confirm resource arguments with `damira_search_vendor_docs` / `damira search-vendor-docs`.

## Providers

| Target | `source` | Auth env vars (keep credentials out of .tf) | Notes |
|---|---|---|---|
| NetBox | `e-breuninger/netbox` | `NETBOX_SERVER_URL`, `NETBOX_API_TOKEN` | Community provider (5.x as of 2026-09). Each release supports a specific NetBox version range — check its README against yours |
| Palo Alto PAN-OS / Panorama | `PaloAltoNetworks/panos` (2.x) | `PANOS_HOSTNAME`, `PANOS_API_KEY` (or `PANOS_USERNAME`/`PANOS_PASSWORD`) | v2 is a rewrite (location blocks, new resource names); v1 docs do not apply. Terraform does not commit — commit via `panos-commit` / API after apply |
| Fortinet FortiOS | `fortinetdev/fortios` (1.x) | `FORTIOS_ACCESS_HOSTNAME`, `FORTIOS_ACCESS_TOKEN` | One resource per CLI table (`fortios_firewall_policy`); set `vdomparam` for non-root VDOMs |
| Cisco Meraki | `CiscoDevNet/meraki` (1.x) | `MERAKI_API_KEY` | Cisco's provider; the cisco-open namespace provider is a stale beta — do not use it. Org/network IDs are inputs, not names |
| Cisco IOS-XE | `CiscoDevNet/iosxe` (1.x) | `IOSXE_HOST`, `IOSXE_USERNAME`, `IOSXE_PASSWORD` | 1.x talks NETCONF over SSH (port 830): `netconf-yang` must be enabled on the device. 1.0 moved off RESTCONF and renamed resources — do not reuse 0.x examples |
| Cisco NX-OS | `CiscoDevNet/nxos` (0.x) | `NXOS_USERNAME`, `NXOS_PASSWORD`, `NXOS_URL` | NX-API REST (`feature nxapi`); still 0.x — breaks between minors, pin exactly |
| Arista EOS / CloudVision | none — no CVaaS provider on the registry | — | The `aristanetworks` namespace publishes only `cloudeos` (cloud VPC networking), not device or CloudVision config. Route EOS/CVaaS changes to generate-playbook (`arista.avd` / `arista.cvp`); never invent resources |

## versions.tf pattern

```hcl
terraform {
  required_version = ">= 1.5" # 1.5.7 is the last MPL release (Homebrew stops there); import blocks need 1.5
  required_providers {
    iosxe = {
      source  = "CiscoDevNet/iosxe"
      version = "~> 1.1" # 1.x: minor updates only. For a 0.x provider (nxos) use "~> 0.14.0" or pin exactly
    }
  }
}
```

## Rules

- `terraform plan -out=tfplan` then `terraform apply tfplan` — never a bare `apply`.
- `for_each` over maps, not `count` — stable keys survive reordering.
- Existing device objects: `import { to = ..., id = ... }` blocks (Terraform ≥ 1.5), then plan
  must show no changes before you add anything.
- Secrets: provider env vars, or `variable { sensitive = true }` fed from `TF_VAR_*`. Never a
  literal in `.tf` or a committed `.tfvars`.
- Shared state: remote backend with locking. Never edit state by hand — `terraform state mv/rm`.
- Prefer implicit dependencies (references) over `depends_on`; a `depends_on` that points back
  at something that references you is a cycle.
- `damira validate` runs `init -backend=false` + `validate` on a throwaway copy, so it needs
  network access to download the providers but leaves nothing in the user's folder.
