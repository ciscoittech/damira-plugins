---
model: haiku
runs: 3
max_turns: 4
timeout_seconds: 180
allowed_tools: [Skill, Read, Glob, Grep]
tags: [triggering, positive]
---

Write the IOS-XE config for our new internet edge router: eBGP to ISP AS 64500 at 198.51.100.1 from our AS 65010 on 198.51.100.2, advertise 203.0.113.0/24 only, with prefix-lists and max-prefix protection.
