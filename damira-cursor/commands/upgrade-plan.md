---
description: Assess a version-to-version upgrade with Damira's upgrade-plan skill
---

Use the Damira `upgrade-plan` skill for this. Follow
`skills/upgrade-plan/SKILL.md`: get the platform, current version, and target
version from the user, then call `~/.damira/bin/damira upgrade-plan` (or the
MCP tool if connected) for the release-note caveats and CVE data, and build
the MOP/change control from the result.

If the user hasn't named a platform and both versions yet, ask for them —
this skill needs a specific version-to-version jump (e.g. IOS-XE 17.6.5 to
17.9.5), not a general "what should I watch out for" question.
