# Hand-off: pyATS / Genie before-and-after diff

pyATS answers "did the change do what the intent says, and nothing else". It reads device
state; in advisor mode it never changes it. Each call that reaches a device is shown to
the engineer to approve, and config pushes through pyATS are blocked.

## Testbed

The `~~testing` server needs a testbed: the devices, how to connect, and credentials. Build
it from the Step 1 devices, not from memory.

```yaml
testbed:
  credentials:
    default:
      username: "%ENV{PYATS_USERNAME}"
      password: "%ENV{PYATS_PASSWORD}"
devices:
  chi-acc-01:
    os: iosxe
    type: switch
    connections:
      cli:
        protocol: ssh
        ip: 10.20.0.11
```

Credentials stay as `%ENV{...}` references. pyATS contrib can also build a testbed straight
from NetBox (`pyats create testbed netbox ...`); check the installed version's options.

## Pick the features to learn

Learn only what the change touches, so the diff is readable:

| Change | Genie features |
|---|---|
| VLANs, access/trunk ports | `vlan`, `interface` |
| Routing (OSPF, BGP, static) | `ospf` or `bgp`, `routing` |
| Addressing | `interface`, `arp` |
| NTP, AAA, SNMP, logging | `ntp`, parsed `show running-config` sections |

## Before the change

Take the pre snapshot with the `~~testing` server's learn or parse tools, per device in the
limit. Save it under `notes/pyats/pre/`. Check it against the intent: a device already in
the intended state needs no change, and that's worth saying.

## After the engineer applies

When the engineer says the change is in, take the post snapshot of the same features into
`notes/pyats/post/` and diff the two. Report:

- the differences the intent predicted (the change worked)
- differences it did not predict (collateral change: flag these first)
- intended values still missing (the change didn't land)

## Without the MCP server

The same flow from the engineer's terminal:

```bash
genie learn vlan interface --testbed-file testbed.yaml --devices chi-acc-01 --output notes/pyats/pre
# engineer applies the change
genie learn vlan interface --testbed-file testbed.yaml --devices chi-acc-01 --output notes/pyats/post
genie diff notes/pyats/pre notes/pyats/post --output notes/pyats/diff
```
