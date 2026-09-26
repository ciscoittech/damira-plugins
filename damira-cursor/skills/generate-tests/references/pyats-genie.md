# pyATS and Genie

Reference pack 1.0 (2026-09-24), condensed from Damira's server skill `pyats-testing`.

## Testbed

```yaml
testbed:
  name: change-1234
  credentials:
    default:
      username: "%ENV{NET_USERNAME}"
      password: "%ENV{NET_PASSWORD}"
devices:
  rtr1:
    os: iosxe            # iosxe, ios, nxos, iosxr, eos, junos, linux ...
    type: router
    connections:
      cli: {protocol: ssh, ip: 192.0.2.1}
```

`%ENV{}` is resolved by pyATS at load time; never put credential literals in the testbed.
`pyats create testbed interactive` can bootstrap one.

## learn → change → learn → diff

```python
from genie.testbed import load
from genie.utils.diff import Diff

tb = load("tests/network/testbed.yml")
dev = tb.devices["rtr1"]
dev.connect(log_stdout=False)
pre = dev.learn("bgp")          # features: bgp, ospf, interface, vlan, routing, platform, ...
# ... change ...
post = dev.learn("bgp")
diff = Diff(pre.info, post.info, exclude=["up_time", "last_reset", "counters"])
diff.findDiff()
print(diff)                      # empty diff == nothing changed
```

- `learn()` = whole feature model (multi-command, OS-agnostic keys); `parse("show ...")` =
  one command → dict. `parse()` raises `SchemaEmptyParserError` on empty output — catch it.
  `learn()` does not raise: it returns the Ops object and records per-command failures, so
  check that `post.info` actually holds the keys you assert on.
- Exclude volatile keys (`up_time`, `counters`, timers) or every diff is noise.
- Save snapshots with `pyats learn bgp ospf --testbed-file testbed.yml --output snapshots/pre`,
  diff with `pyats diff snapshots/pre snapshots/post`.

## AEtest structure

```
CommonSetup      @aetest.subsection connect
Testcase(s)      @aetest.setup, @aetest.test (one assertion per test), self.failed()/passed()/skipped()
CommonCleanup    disconnect
```

Run from a job: `pyats run job job.py --testbed-file testbed.yml`; `pyats logs view` for the
HTML report. Parametrise with `aetest.loop.mark(Testcase, device=[...])`.

## pytest for scripts

- Mock the connection where it is looked up: `monkeypatch.setattr(mymodule,
  "ConnectHandler", FakeConn)`. A script that did `from netmiko import ConnectHandler` never
  sees a patch on `netmiko` itself. Or build Nornir `Result` objects directly; test parsing
  and decisions, not the device.
- Fixture files with captured show output under `tests/fixtures/`.
- No test ever opens a real session.
