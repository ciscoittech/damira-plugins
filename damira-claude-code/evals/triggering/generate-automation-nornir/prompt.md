---
model: haiku
runs: 3
max_turns: 4
timeout_seconds: 180
allowed_tools: [Skill, Read, Glob, Grep]
tags: [triggering, positive]
---

Write me a Nornir script that backs up the running config of every device in our inventory to a dated folder and reports which devices failed.
