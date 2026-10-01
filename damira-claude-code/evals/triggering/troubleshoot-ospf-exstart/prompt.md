---
model: haiku
runs: 3
max_turns: 4
timeout_seconds: 180
allowed_tools: [Skill, Read, Glob, Grep]
tags: [triggering, positive]
---

OSPF between our two Catalyst 9300s (IOS-XE 17.9) has been stuck in EXSTART since this morning's change window. show ip ospf neighbor on core-1 shows core-2 in EXSTART/DR on Te1/0/1. What's going on and how do I fix it?
