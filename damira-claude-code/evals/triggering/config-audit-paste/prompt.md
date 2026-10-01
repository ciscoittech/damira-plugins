---
model: haiku
runs: 3
max_turns: 4
timeout_seconds: 180
allowed_tools: [Skill, Read, Glob, Grep]
tags: [triggering, positive]
---

Here's the running config from our branch router, can you look at it?

```
hostname BR-RTR-01
enable password cisco123
username admin password 0 admin
line vty 0 4
 transport input telnet ssh
 password cisco
 login
snmp-server community public RW
ip http server
no service password-encryption
interface GigabitEthernet0/0
 ip address 203.0.113.2 255.255.255.252
```
