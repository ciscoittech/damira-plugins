---
model: haiku
runs: 3
max_turns: 4
timeout_seconds: 180
allowed_tools: [Skill, Read, Glob, Grep]
tags: [triggering, positive]
---

Draw a topology diagram of our campus: two core 9500s in a VSS pair, four distribution 9300 stacks dual-homed to the cores, and a pair of firewalls north of the core to the internet.
