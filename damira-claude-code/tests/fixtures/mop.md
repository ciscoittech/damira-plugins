# MOP: IOS-XE 17.6.5 to 17.9.5 Upgrade

**Change ID:** CHG-0042 · **Risk:** Medium

## Pre-Maintenance Verification

| Device | Mgmt IP | Check | Expected |
|--------|---------|-------|----------|
| chi-core-rtr-01 | 10.20.30.40 | `show version` | 17.6.5 |
| chi-core-rtr-02 | 10.20.30.41 | `show install summary` | Committed |

## Step-by-Step Procedure

1. Copy the image to flash.
2. Activate: **reload required**.

```
install add file flash:cat9k_iosxe.17.09.05.SPA.bin activate commit
snmp-server community S3cr3tRO RO
```

## Notes

Operator note: <script>alert(1)</script>
