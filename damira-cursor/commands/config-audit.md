---
description: Security-audit a device config with Damira's config-audit skill
---

Use the Damira `config-audit` skill for this. Follow
`skills/config-audit/SKILL.md`: get the config (file reference or pasted
text), run `~/.damira/bin/damira-audit-config` on it, and present the
findings with severity ratings. Do not review the config by eye only — the
script catches patterns a manual read misses.

If the user hasn't provided a config yet, ask them to paste it or point at
the file.
