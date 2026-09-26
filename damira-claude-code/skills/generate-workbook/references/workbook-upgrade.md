# Upgrade workbook

Use for a version-to-version upgrade of one platform (IOS-XE, CUCM, PAN-OS, NX-OS, FortiOS, Junos, ...).

**Shape:** Pre-Checks / Implementation Steps / Post-Checks. Every procedure workbook follows the same three phases:
verify readiness and record baselines, do the work step by step, then verify the
result against the baselines.

## Rules for filling it in
- Row keys are the header in lower case with spaces as underscores
  (`"CLI Command"` becomes `cli_command`).
- Anything only the engineer knows (names, IPs, dates, change numbers) is a
  `[BRACKETED PLACEHOLDER]` in an `input_columns` column. Those cells render yellow and
  stay editable.
- Command cells (`CLI Command`, `Command`, `Verification Command`, `Check`) are
  grounding-checked against `documents/<id>/evidence/`. If you can't back a command
  with saved Damira evidence, write `[VERIFY: what to confirm]` rather than guessing.
  The renderer tags any other unbacked command UNVERIFIED. A step with no command
  (GUI navigation, a manual test) starts `GUI:` or `Manual:`; those cells are skipped,
  so UNVERIFIED stays reserved for commands.
- `dropdowns` are comma-separated options. `conditional_rules` types: `status`,
  `pass_fail`, `yes_no`, `risk_score`.
- `auto_id_prefix` numbers the first column (`PRE-001`, ...). `formulas` use
  `{Header Name}` placeholders that resolve to that row's cell.
- Put every bug ID, CVE, and upgrade-path fact from the release-notes and CVE lookups in a row with the matching command. The installer command and the rollback trigger are the cells engineers copy, so they must come from the evidence.

## Example spec
The example below is illustrative structure. Replace every value with the user's
environment and the evidence. Don't copy its commands.

```json
{
  "title": "CUCM 14 to 15 Upgrade",
  "summary_fields": {
    "Product": "CUCM",
    "Current Version": "14.0 SU4",
    "Target Version": "15.0 SU1",
    "Nodes": "2 (Publisher + Subscriber)",
    "Engineer": "[YOUR NAME]",
    "Maintenance Window": "[DATE TIME - TIME]"
  },
  "executive_summary": "Upgrade 2-node CUCM cluster from 14.0 SU4 to 15.0 SU1. Publisher first, then subscriber. Estimated 5-7 hours.",
  "sheets": [
    {
      "name": "Pre-Checks",
      "headers": [
        "#",
        "Check",
        "CLI Command",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "check": "Verify current version",
          "cli_command": "show version active",
          "expected_result": "14.0.1.xxxxx (SU4)",
          "what_you_need": "Publisher IP, OS Admin creds"
        },
        {
          "check": "Run pre-upgrade COP file",
          "cli_command": "GUI: OS Admin > Install ciscocm.preUpgradeCheck-00019.cop.sgn",
          "expected_result": "All checks pass",
          "what_you_need": "Publisher IP, COP file (download from cisco.com)"
        },
        {
          "check": "Verify ESXi version",
          "cli_command": "GUI: vSphere Client",
          "expected_result": "ESXi 7.0 U3 or 8.0 U1+",
          "what_you_need": "vCenter IP, vCenter creds"
        },
        {
          "check": "Verify VM disk size",
          "cli_command": "GUI: vSphere Client",
          "expected_result": "110 GB minimum",
          "what_you_need": "vCenter IP"
        },
        {
          "check": "Verify VMXNET3 adapter",
          "cli_command": "GUI: vSphere Client > VM Settings",
          "expected_result": "Network adapter = VMXNET3",
          "what_you_need": "vCenter IP"
        },
        {
          "check": "Check DB replication",
          "cli_command": "utils dbreplication runtimestate",
          "expected_result": "Replication setup value = 2",
          "what_you_need": "Publisher IP, SSH creds"
        },
        {
          "check": "Generate DB status report",
          "cli_command": "GUI: Cisco Unified Reporting > System Reports > Unified CM Database Status",
          "expected_result": "No errors",
          "what_you_need": "Publisher IP, OS Admin creds"
        },
        {
          "check": "Check NTP sync",
          "cli_command": "utils ntp status",
          "expected_result": "NTP synchronized, low offset",
          "what_you_need": "NTP server IP"
        },
        {
          "check": "Check DNS resolution",
          "cli_command": "utils network dns diagnose",
          "expected_result": "All lookups succeed",
          "what_you_need": "DNS server IPs"
        },
        {
          "check": "Check expired certificates",
          "cli_command": "GUI: OS Admin > Security > Certificate Management",
          "expected_result": "No expired certs",
          "what_you_need": "Publisher IP, OS Admin creds"
        },
        {
          "check": "Verify Smart Licensing",
          "cli_command": "GUI: CM Admin > System > Licensing > License Usage Report",
          "expected_result": "Sufficient licenses for v15",
          "what_you_need": "Smart Account ID, license type"
        },
        {
          "check": "Check IPSec policies (FIPS)",
          "cli_command": "GUI: OS Admin > Security > IPSec Configuration",
          "expected_result": "No DH groups 17/18 (blocked in 15SU3+)",
          "what_you_need": "Publisher IP"
        },
        {
          "check": "Run CLI diagnostics",
          "cli_command": "utils diagnose test",
          "expected_result": "No critical errors",
          "what_you_need": "Publisher IP, SSH creds"
        },
        {
          "check": "Check disk space",
          "cli_command": "show status",
          "expected_result": "Sufficient common partition space",
          "what_you_need": "Publisher + Subscriber IPs"
        },
        {
          "check": "Record registered device count",
          "cli_command": "GUI: RTMT > Device > Device Summary",
          "expected_result": "Record baseline count",
          "what_you_need": "Publisher IP, RTMT client"
        },
        {
          "check": "Record assigned user count",
          "cli_command": "GUI: CM Admin > User Management > End User (count)",
          "expected_result": "Record baseline count",
          "what_you_need": "Publisher IP"
        },
        {
          "check": "Record TFTP parameters",
          "cli_command": "GUI: CM Admin > System > Service Parameters > TFTP",
          "expected_result": "Screenshot/record current values",
          "what_you_need": "Publisher IP"
        },
        {
          "check": "Record enterprise parameters",
          "cli_command": "GUI: CM Admin > System > Enterprise Parameters",
          "expected_result": "Screenshot/record current values",
          "what_you_need": "Publisher IP"
        },
        {
          "check": "Take DRS backup (Publisher)",
          "cli_command": "utils disaster_recovery backup network",
          "expected_result": "Backup completed successfully",
          "what_you_need": "SFTP server IP, path, creds"
        },
        {
          "check": "Take DRS backup (Subscriber)",
          "cli_command": "utils disaster_recovery backup network",
          "expected_result": "Backup completed successfully",
          "what_you_need": "SFTP server IP, path, creds"
        },
        {
          "check": "Backup custom ringtones/images",
          "cli_command": "Manual: SFTP download from TFTP directory",
          "expected_result": "Files saved externally",
          "what_you_need": "Publisher IP, SFTP creds"
        },
        {
          "check": "Suspend LDAP synchronization",
          "cli_command": "GUI: CM Admin > System > LDAP > LDAP Directory > uncheck sync",
          "expected_result": "Sync disabled",
          "what_you_need": "Publisher IP, LDAP server info"
        },
        {
          "check": "Add serial port to VM",
          "cli_command": "GUI: vSphere Client > VM Settings > Add Serial Port",
          "expected_result": "Serial port available for log dump",
          "what_you_need": "vCenter IP"
        },
        {
          "check": "Download upgrade ISO + COP files",
          "cli_command": "Manual: download from cisco.com to the SFTP server",
          "expected_result": "Files staged on SFTP",
          "what_you_need": "Target version, SFTP server, Cisco CCO account"
        },
        {
          "check": "Verify upgrade files accessible",
          "cli_command": "Manual: confirm SFTP connectivity from the Publisher",
          "expected_result": "Publisher can reach SFTP",
          "what_you_need": "SFTP server IP, creds"
        }
      ],
      "input_columns": [
        "Actual",
        "Pass?"
      ],
      "dropdowns": {
        "Pass?": "Pass,Fail,N/A,Skipped"
      },
      "conditional_rules": [
        {
          "column": "Pass?",
          "type": "status"
        }
      ],
      "auto_id_prefix": "P"
    },
    {
      "name": "Implementation Steps",
      "headers": [
        "#",
        "Action",
        "CLI Command",
        "Expected Result",
        "Rollback",
        "Time Est.",
        "What You Need",
        "Status"
      ],
      "rows": [
        {
          "action": "Configure reboot sequence",
          "cli_command": "GUI: OS Admin > Software Upgrades > Restart/Switch-Version Cluster",
          "expected_result": "Reboot order set (Pub first)",
          "rollback": "N/A",
          "time_est": "5 min",
          "what_you_need": "Publisher IP, OS Admin creds"
        },
        {
          "action": "Configure cluster software location",
          "cli_command": "GUI: OS Admin > Software Upgrades > Cluster Software Location",
          "expected_result": "SFTP source configured for all nodes",
          "rollback": "N/A",
          "time_est": "5 min",
          "what_you_need": "SFTP server, directory, creds"
        },
        {
          "action": "Start clusterwide upgrade",
          "cli_command": "utils system upgrade initiate",
          "expected_result": "Upgrade initiated on Publisher",
          "rollback": "utils system switch-version",
          "time_est": "2-4 hrs",
          "what_you_need": "Publisher IP, OS Admin creds, ISO filename"
        },
        {
          "action": "Monitor upgrade progress",
          "cli_command": "GUI: OS Admin > Installation Status page",
          "expected_result": "Upgrade completes without errors",
          "rollback": "Check install logs via RTMT",
          "time_est": "—",
          "what_you_need": "Publisher IP"
        },
        {
          "action": "Switch version (if manual)",
          "cli_command": "utils system switch-version",
          "expected_result": "Cluster reboots to 15.0 SU1",
          "rollback": "utils system switch-version",
          "time_est": "30 min",
          "what_you_need": "Publisher IP, SSH or OS Admin creds"
        },
        {
          "action": "Wait for Publisher services",
          "cli_command": "utils service list",
          "expected_result": "All critical services started",
          "rollback": "Investigate service failures",
          "time_est": "15 min",
          "what_you_need": "Publisher IP"
        },
        {
          "action": "Wait for Subscriber upgrade + reboot",
          "cli_command": "GUI: Publisher OS Admin > Installation Status",
          "expected_result": "Subscriber on 15.0 SU1",
          "rollback": "utils system switch-version on Sub",
          "time_est": "1-2 hrs",
          "what_you_need": "Subscriber IP"
        },
        {
          "action": "Wait for DB replication",
          "cli_command": "utils dbreplication runtimestate",
          "expected_result": "Replication setup value = 2",
          "rollback": "utils dbreplication repair all",
          "time_est": "30 min",
          "what_you_need": "Publisher IP"
        },
        {
          "action": "Run post-upgrade COP file",
          "cli_command": "GUI: OS Admin > Install ciscocm.postUpgradeCheck-XXXXX.cop.sgn",
          "expected_result": "All post-upgrade checks pass",
          "rollback": "Address any failures",
          "time_est": "10 min",
          "what_you_need": "Publisher IP, post-upgrade COP file"
        }
      ],
      "input_columns": [
        "Status"
      ],
      "dropdowns": {
        "Status": "Not Started,In Progress,Done,Failed,Rolled Back"
      },
      "conditional_rules": [
        {
          "column": "Status",
          "type": "status"
        }
      ],
      "auto_id_prefix": "U"
    },
    {
      "name": "Post-Checks",
      "headers": [
        "#",
        "Check",
        "CLI Command",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "check": "Verify Publisher version",
          "cli_command": "show version active",
          "expected_result": "15.0.1.xxxxx (SU1)",
          "what_you_need": "Publisher IP"
        },
        {
          "check": "Verify Subscriber version",
          "cli_command": "show version active",
          "expected_result": "15.0.1.xxxxx (SU1)",
          "what_you_need": "Subscriber IP"
        },
        {
          "check": "Verify DB replication",
          "cli_command": "utils dbreplication runtimestate",
          "expected_result": "Replication setup value = 2",
          "what_you_need": "Publisher IP"
        },
        {
          "check": "Verify device registration count",
          "cli_command": "GUI: RTMT > Device > Device Summary",
          "expected_result": "Matches pre-upgrade baseline",
          "what_you_need": "Publisher IP, RTMT, baseline from Pre-Check"
        },
        {
          "check": "Verify assigned user count",
          "cli_command": "GUI: CM Admin > User Management > End User",
          "expected_result": "Matches pre-upgrade baseline",
          "what_you_need": "Publisher IP, baseline from Pre-Check"
        },
        {
          "check": "Reset TFTP parameters",
          "cli_command": "GUI: CM Admin > System > Service Parameters > TFTP",
          "expected_result": "Matches pre-upgrade values",
          "what_you_need": "Publisher IP, recorded values from Pre-Check"
        },
        {
          "check": "Restore enterprise parameters",
          "cli_command": "GUI: CM Admin > System > Enterprise Parameters",
          "expected_result": "Matches pre-upgrade values",
          "what_you_need": "Publisher IP, recorded values from Pre-Check"
        },
        {
          "check": "Update CTL file (if mixed mode)",
          "cli_command": "utils ctl update CTLFile",
          "expected_result": "CTL updated, phones reset",
          "what_you_need": "Publisher IP, Security Token (USB)"
        },
        {
          "check": "Remove serial port from VM",
          "cli_command": "GUI: vSphere Client > VM Settings > Remove Serial Port",
          "expected_result": "Serial port removed",
          "what_you_need": "vCenter IP"
        },
        {
          "check": "Update VMware Tools",
          "cli_command": "Manual: install Open VM Tools (v15 requirement)",
          "expected_result": "Open VM Tools installed",
          "what_you_need": "vCenter IP"
        },
        {
          "check": "Restart Extension Mobility",
          "cli_command": "utils service restart Cisco Extension Mobility",
          "expected_result": "Service restarted",
          "what_you_need": "Publisher IP"
        },
        {
          "check": "Test internal call",
          "cli_command": "Manual: call between two registered phones",
          "expected_result": "Call connects, audio good",
          "what_you_need": "Two test phone DNs"
        },
        {
          "check": "Test voicemail",
          "cli_command": "Manual: dial VM pilot, leave and retrieve message",
          "expected_result": "VM deposit and retrieval work",
          "what_you_need": "Unity Connection pilot number"
        },
        {
          "check": "Test MRA (if Expressway)",
          "cli_command": "Manual: Jabber login via Expressway",
          "expected_result": "Jabber registers via MRA",
          "what_you_need": "Expressway IPs, test Jabber account"
        },
        {
          "check": "Resume LDAP synchronization",
          "cli_command": "GUI: CM Admin > System > LDAP > LDAP Directory > enable sync",
          "expected_result": "Sync running, users updated",
          "what_you_need": "Publisher IP, LDAP server info"
        },
        {
          "check": "Upgrade integrated products",
          "cli_command": "Manual: per-product upgrade procedure",
          "expected_result": "Unity, Expressway, IM&P on compatible versions",
          "what_you_need": "Product IPs, ISOs"
        },
        {
          "check": "Install locales (if needed)",
          "cli_command": "GUI: OS Admin > Software Upgrades > Install locale COP",
          "expected_result": "Locale installed",
          "what_you_need": "Locale COP files"
        },
        {
          "check": "Upgrade RTMT client",
          "cli_command": "GUI: CM Admin > download CiscoRTMTPlugin.zip",
          "expected_result": "RTMT updated on workstation",
          "what_you_need": "RTMT workstation, new plugin"
        }
      ],
      "input_columns": [
        "Actual",
        "Pass?"
      ],
      "dropdowns": {
        "Pass?": "Pass,Fail,N/A,Skipped"
      },
      "conditional_rules": [
        {
          "column": "Pass?",
          "type": "status"
        }
      ],
      "auto_id_prefix": "V"
    }
  ]
}
```
