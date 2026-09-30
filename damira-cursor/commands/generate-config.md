---
description: Write a deployable device config with Damira's generate-config skill
---

Use the Damira `generate-config` skill for this. Follow
`skills/generate-config/SKILL.md`: gather the device, platform/OS version,
features, interfaces, and hostname, verify uncertain syntax with
`~/.damira/bin/damira search-vendor-docs`, and produce the deployable config.

If the user hasn't said what device/platform and feature (BGP, OSPF, VLANs,
ACLs, NAT, NTP, AAA, SNMP, ...) they need, ask before writing anything.
