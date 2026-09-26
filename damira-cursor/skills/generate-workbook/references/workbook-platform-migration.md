# Platform migration workbook

Use for moving from one platform to another (CUCM to Webex Calling, ASA to FTD, on-prem to cloud).

**Shape:** Pre-Migration / Migration Steps / Post-Migration. Every procedure workbook follows the same three phases:
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
  The renderer tags any other unbacked command UNVERIFIED.
- `dropdowns` are comma-separated options. `conditional_rules` types: `status`,
  `pass_fail`, `yes_no`, `risk_score`.
- `auto_id_prefix` numbers the first column (`PRE-001`, ...). `formulas` use
  `{Header Name}` placeholders that resolve to that row's cell.
- Feature-parity gaps between the source and target platforms are the main risk. List each one as a row, backed by the vendor-docs lookup.

## Example spec
The example below is illustrative structure. Replace every value with the user's
environment and the evidence. Don't copy its commands.

```json
{
  "title": "CUCM to Webex Calling Migration",
  "summary_fields": {
    "Source Platform": "CUCM 14 SU4 (on-prem)",
    "Target Platform": "Webex Calling (cloud)",
    "Users": "500",
    "Sites": "2 (HQ + Branch)",
    "Engineer": "[YOUR NAME]",
    "Migration Timeline": "6 months (phased)"
  },
  "executive_summary": "Phased migration of 500 users from on-prem CUCM 14 to Webex Calling. Includes Unity Connection voicemail migration, Expressway MRA decommission (replaced by Webex App), SIP trunk cutover to Local Gateway, and number porting.",
  "sheets": [
    {
      "name": "Pre-Checks",
      "headers": [
        "#",
        "Check",
        "Action",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "check": "Webex Control Hub access",
          "action": "Verify admin access to admin.webex.com",
          "expected_result": "Full admin rights confirmed",
          "what_you_need": "Control Hub admin creds, Webex org ID"
        },
        {
          "check": "Licensing",
          "action": "Verify sufficient Webex Calling licenses in Control Hub",
          "expected_result": "500+ Calling licenses available",
          "what_you_need": "Control Hub > Subscriptions"
        },
        {
          "check": "Locations configured",
          "action": "Create locations in Control Hub matching physical sites",
          "expected_result": "HQ + Branch locations created with E911 addresses",
          "what_you_need": "Site addresses, E911 info"
        },
        {
          "check": "PSTN connectivity",
          "action": "Decide PSTN approach: Cisco PSTN, Cloud Connected PSTN, or Local Gateway",
          "expected_result": "PSTN approach selected and documented",
          "what_you_need": "Current SIP trunk provider info, pricing"
        },
        {
          "check": "Local Gateway setup",
          "action": "Deploy and configure CUBE/SBC as Webex Local Gateway",
          "expected_result": "Local Gateway registered to Control Hub",
          "what_you_need": "CUBE/SBC IP, Webex trunk config, certs"
        },
        {
          "check": "Number inventory",
          "action": "Export all DNs, translation patterns, route patterns from CUCM",
          "expected_result": "Complete number inventory spreadsheet",
          "what_you_need": "CUCM admin creds, BAT export"
        },
        {
          "check": "Number porting prep",
          "action": "Submit LOA to carrier for number porting to Webex",
          "expected_result": "LOA accepted, port date scheduled",
          "what_you_need": "Carrier account, LOA form, CSR (Customer Service Record)"
        },
        {
          "check": "Dial plan mapping",
          "action": "Map CUCM route patterns/translation patterns to Webex dial plan",
          "expected_result": "Dial plan mapping document complete",
          "what_you_need": "CUCM dial plan export, Webex dial plan template"
        },
        {
          "check": "Voicemail strategy",
          "action": "Decide: migrate Unity Connection to Webex Voicemail or keep hybrid",
          "expected_result": "Voicemail approach documented",
          "what_you_need": "Unity Connection version, greeting/message migration plan"
        },
        {
          "check": "Device compatibility",
          "action": "Check which phones support Webex Calling (MPP firmware)",
          "expected_result": "Device compatibility list with migration/replace decisions",
          "what_you_need": "Phone model inventory from CUCM"
        },
        {
          "check": "User migration groups",
          "action": "Define pilot group (10-20 users), then department waves",
          "expected_result": "Migration wave plan with dates",
          "what_you_need": "Org chart, department list, user willingness"
        },
        {
          "check": "Webex App deployment",
          "action": "Plan Webex App rollout (desktop + mobile) for migrated users",
          "expected_result": "App deployment method selected (MSI, SCCM, self-install)",
          "what_you_need": "IT deployment tools, Webex App installer"
        },
        {
          "check": "Training plan",
          "action": "Schedule end-user training for Webex App and new phone features",
          "expected_result": "Training sessions scheduled for each wave",
          "what_you_need": "Training materials, calendar slots"
        },
        {
          "check": "Rollback plan",
          "action": "Document how to move users back to CUCM if migration fails",
          "expected_result": "Rollback procedure documented and tested",
          "what_you_need": "CUCM config backup, DN reservation"
        },
        {
          "check": "CUCM backup",
          "action": "Take full DRS backup of CUCM before migration starts",
          "expected_result": "DRS backup completed and verified",
          "what_you_need": "CUCM publisher IP, SFTP server"
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
        "Wave",
        "Action",
        "Details",
        "Rollback",
        "What You Need",
        "Status"
      ],
      "rows": [
        {
          "wave": "Pilot",
          "action": "Provision pilot users in Control Hub",
          "details": "Add 10-20 users to Webex Calling with Calling licenses",
          "rollback": "Remove users from Webex, re-enable on CUCM",
          "what_you_need": "User list (email, DN, device), Control Hub admin"
        },
        {
          "wave": "Pilot",
          "action": "Assign numbers to pilot users",
          "details": "Assign DIDs from ported or new number block",
          "rollback": "Unassign numbers",
          "what_you_need": "DID list, number assignment plan"
        },
        {
          "wave": "Pilot",
          "action": "Configure pilot user devices",
          "details": "Convert phones to MPP firmware or deploy Webex App",
          "rollback": "Revert phone to Enterprise firmware",
          "what_you_need": "Phone MAC addresses, MPP firmware files"
        },
        {
          "wave": "Pilot",
          "action": "Test pilot — internal calls",
          "details": "Pilot users call each other and CUCM users",
          "rollback": "N/A",
          "what_you_need": "Test call plan, pilot user list"
        },
        {
          "wave": "Pilot",
          "action": "Test pilot — external calls",
          "details": "Pilot users make/receive PSTN calls via Local Gateway",
          "rollback": "Route PSTN back through CUCM",
          "what_you_need": "External test numbers, PSTN routing config"
        },
        {
          "wave": "Pilot",
          "action": "Test pilot — voicemail",
          "details": "Verify voicemail deposit and retrieval for pilot users",
          "rollback": "Point MWI back to Unity Connection",
          "what_you_need": "Voicemail test plan"
        },
        {
          "wave": "Pilot",
          "action": "Pilot review — go/no-go for Wave 1",
          "details": "Collect feedback from pilot users, review call quality metrics",
          "rollback": "Extend pilot, fix issues",
          "what_you_need": "Feedback survey, Webex Analytics"
        },
        {
          "wave": "Wave 1",
          "action": "Provision Wave 1 department",
          "details": "Add next department (50-100 users) to Webex Calling",
          "rollback": "Remove users, re-enable on CUCM",
          "what_you_need": "Department user list, DNs, devices"
        },
        {
          "wave": "Wave 1",
          "action": "Port Wave 1 numbers",
          "details": "Execute number port for Wave 1 DIDs",
          "rollback": "Port numbers back to original carrier",
          "what_you_need": "Carrier port order, port date confirmation"
        },
        {
          "wave": "Wave 1",
          "action": "Migrate Wave 1 devices",
          "details": "Convert phones or deploy Webex App to Wave 1 users",
          "rollback": "Revert devices to CUCM registration",
          "what_you_need": "Device list, MPP firmware, Webex App installer"
        },
        {
          "wave": "Wave N",
          "action": "Repeat for remaining departments",
          "details": "Follow same pattern: provision → assign numbers → devices → test → go-live",
          "rollback": "Per-wave rollback procedure",
          "what_you_need": "Wave plan, user lists per department"
        },
        {
          "wave": "Final",
          "action": "Port remaining numbers",
          "details": "Execute final number port for all remaining DIDs",
          "rollback": "Emergency port-back via carrier",
          "what_you_need": "Final port order, carrier coordination"
        },
        {
          "wave": "Final",
          "action": "Decommission CUCM SIP trunks",
          "details": "Remove SIP trunks from CUCM pointing to PSTN",
          "rollback": "Re-add SIP trunk config (saved in backup)",
          "what_you_need": "CUCM admin creds, trunk config backup"
        },
        {
          "wave": "Final",
          "action": "Decommission Unity Connection",
          "details": "Shut down Unity Connection after all voicemail migrated",
          "rollback": "Power on Unity Connection VM",
          "what_you_need": "Unity Connection VM, voicemail migration verification"
        },
        {
          "wave": "Final",
          "action": "Decommission Expressway",
          "details": "Shut down Expressway-C/E after MRA replaced by Webex App",
          "rollback": "Power on Expressway VMs",
          "what_you_need": "Expressway VMs, MRA user verification"
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
      "auto_id_prefix": "M"
    },
    {
      "name": "Post-Checks",
      "headers": [
        "#",
        "Check",
        "Action",
        "Expected Result",
        "Actual",
        "What You Need",
        "Pass?"
      ],
      "rows": [
        {
          "check": "All users registered",
          "action": "Verify all 500 users show Active in Control Hub",
          "expected_result": "500 users active with Calling license",
          "what_you_need": "Control Hub > Users"
        },
        {
          "check": "All numbers ported",
          "action": "Verify all DIDs are active in Webex Calling",
          "expected_result": "All DIDs answering on Webex",
          "what_you_need": "Number inventory, test calls to each DID block"
        },
        {
          "check": "Internal calling",
          "action": "Test internal calls between Webex users",
          "expected_result": "Calls connect, audio clear",
          "what_you_need": "Test call plan"
        },
        {
          "check": "External calling",
          "action": "Test inbound + outbound PSTN calls",
          "expected_result": "PSTN calls route correctly via Local Gateway",
          "what_you_need": "External test numbers"
        },
        {
          "check": "Voicemail",
          "action": "Test voicemail deposit and retrieval",
          "expected_result": "VM works for all users",
          "what_you_need": "Test voicemail accounts"
        },
        {
          "check": "E911",
          "action": "Verify E911 routing for all locations",
          "expected_result": "E911 calls route to correct PSAP",
          "what_you_need": "E911 test procedure (non-emergency)"
        },
        {
          "check": "Call quality",
          "action": "Review Webex Analytics for MOS, jitter, packet loss",
          "expected_result": "MOS > 3.5, jitter < 30ms, loss < 1%",
          "what_you_need": "Control Hub > Analytics > Calling"
        },
        {
          "check": "Device registration",
          "action": "Verify all phones/Webex Apps registered",
          "expected_result": "Device count matches inventory",
          "what_you_need": "Control Hub > Devices"
        },
        {
          "check": "Auto-attendant/hunt groups",
          "action": "Verify call queues and auto-attendants working",
          "expected_result": "All call flows functional",
          "what_you_need": "Call flow test plan"
        },
        {
          "check": "CUCM decommissioned",
          "action": "Verify CUCM publisher and subscribers powered off",
          "expected_result": "VMs shut down, resources reclaimed",
          "what_you_need": "vCenter access"
        },
        {
          "check": "Documentation updated",
          "action": "Update network diagrams, runbooks, and support contacts",
          "expected_result": "All docs reflect Webex Calling",
          "what_you_need": "Documentation templates"
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
