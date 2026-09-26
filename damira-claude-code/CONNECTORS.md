# Connectors

Damira drafts ecosystem records. The engineer's own MCP connectors write them. The plugin
ships no ServiceNow, Jira, Slack or PagerDuty connector and holds no credentials for them.

Skills refer to connectors by category placeholder, never by tool name. The same connector
appears as `mcp__atlassian__*`, `mcp__plugin_<plugin>_<server>__*`, or a UUID for a claude.ai
connector, depending on how it was installed. To resolve a placeholder, find the tools with
tool search, then check the **Ecosystem** section that `damira init` writes to CLAUDE.md or
AGENTS.md. At session start the plugin also lists, by category and by name only, the MCP
servers it finds in `.mcp.json` and `~/.claude.json` (Claude Code) or `.cursor/mcp.json` and
`~/.cursor/mcp.json` (Cursor). That list is not complete: servers from other plugins,
`managed-mcp.json`, claude.ai connectors and Cursor marketplace servers don't appear in it, so
tool search is still the way to find them.

**Rule:** Damira drafts the record, the engineer reviews it, and only then does the
connector write it. Nothing is written to a ticketing or chat system without that confirmation.

## Categories

| Placeholder | Used for | Example connectors |
|---|---|---|
| `~~itsm` | Change requests, incidents, CAB records | ServiceNow, Jira Service Management, Freshservice, Zendesk, BMC Helix |
| `~~tracker` | Tasks and follow-ups from a MOP or post-incident review | Jira, Linear, monday, Asana, GitHub, GitLab |
| `~~chat` | Incident updates and change notices to a channel | Slack, Microsoft Teams, Webex |
| `~~paging` | Who is on call, acknowledging or escalating a page | PagerDuty, Opsgenie, incident.io |
| `~~observability` | Metrics, logs and alerts as troubleshooting evidence | Datadog, Splunk, Grafana, Prometheus, ThousandEyes |
| `~~source-of-truth` | Devices, sites, IPs, CMDB CI lookups | NetBox, Nautobot, Infoblox, IP Fabric |
| `~~docs` | Publishing MOPs, runbooks and incident reports | Confluence, Notion, SharePoint, Google Drive |

Set the defaults once with `damira init`:

```bash
damira init --ecosystem "itsm=ServiceNow:NetOps" --ecosystem "chat=Slack:#noc-changes" \
  --ecosystem "tracker=Jira:NET" --change-type normal
```

The part after `:` is the assignment group or project for `~~itsm`, the project key for
`~~tracker`, the channel for `~~chat`, and the service for `~~paging`.

`--change-type` takes `standard`, `normal` or `emergency`, which are the ServiceNow values.
Freshservice stores `change_type` as an integer (1 minor, 2 standard, 3 major, 4 emergency),
so map the value before writing: `standard` is 2, `emergency` is 4, and `normal` is 1 or 3
depending on the risk.

## Record schemas

Vendor field names are the usual defaults. Jira/JSM custom fields and monday columns are
named per site, so confirm them against the connector before writing. An entry written as
words rather than a field name (for example `associated ticket` or `parent ticket/change` in
Freshservice) is a relationship made through the vendor's association API, not one field. ServiceNow follows the
agent's ticketing rules: category is one of network, hardware, software, security, telecom or
request, and subcategory is one of routing, switching, firewall, wireless, voice, vpn, dns, ntp
or certificate. Impact and urgency come from priority (P1 is 1, P2-P3 are 2, P4-P5 are 3). The
assignment group defaults to Network Operations Center for P1-P2 and Network Engineering
otherwise.

### `change_request`

`validate_report` is the output of `damira validate` on the generated automation. A change request without it, or without implementation, backout and test plans, is not ready for CAB.

| Field | Required | ServiceNow | Jira/JSM | monday | Freshservice |
|---|---|---|---|---|---|
| `title` | yes | `short_description` | `summary` | `item name` | `subject` |
| `description` | yes | `description` | `description` | `Description (long text)` | `description` |
| `change_type` | yes | `type` | `Change type` | `Change type (status)` | `change_type` |
| `cmdb_ci` | yes | `cmdb_ci` | `Affected services / Assets object` | `CI / device (text or connect)` | `assets` |
| `risk` | yes | `risk` | `Change risk` | `Risk (status)` | `risk` |
| `impact` | yes | `impact` | `Impact` | `Impact (status)` | `impact` |
| `assignment_group` | yes | `assignment_group` | `Team` | `Team (people)` | `group_id` |
| `planned_start` | yes | `start_date` | `Planned start` | `Timeline (start)` | `planned_start_date` |
| `planned_end` | yes | `end_date` | `Planned end` | `Timeline (end)` | `planned_end_date` |
| `implementation_plan` | yes | `implementation_plan` | `Implementation plan` | `Implementation plan (long text)` | `planning_fields.rollout_plan` |
| `backout_plan` | yes | `backout_plan` | `Backout plan` | `Backout plan (long text)` | `planning_fields.backout_plan` |
| `test_plan` | yes | `test_plan` | `Test plan` | `Test plan (long text)` | `custom_fields.test_plan` |
| `validate_report` | yes | `work_notes` | `internal comment` | `update` | `private note` |
| `justification` |  | `justification` | `Change reason` | `Justification (long text)` | `planning_fields.reason_for_change` |
| `category` |  | `category` | `Request type` | `Category (status)` | `category` |
| `affected_devices` |  | `task_ci (affected CIs)` | `Assets objects` | `Devices (connect boards)` | `assets` |
| `related_ref` |  | `parent` | `linked issue` | `Linked item (connect boards)` | `associated ticket` |

### `incident_update`

Post the same update to `~~chat` if the engineer has an incident channel.

| Field | Required | ServiceNow | Jira/JSM | monday | Freshservice |
|---|---|---|---|---|---|
| `incident_ref` | yes | `number` | `issue key` | `item ID` | `ticket id` |
| `status` | yes | `state` | `status (transition)` | `Status (status)` | `status` |
| `summary` | yes | `short_description` | `summary` | `item name` | `subject` |
| `impact` | yes | `impact` | `Impact` | `Impact (status)` | `impact` |
| `cmdb_ci` | yes | `cmdb_ci` | `Affected services / Assets object` | `CI / device (text or connect)` | `assets` |
| `work_note` | yes | `work_notes` | `internal comment` | `update` | `private note` |
| `next_update` | yes | `work_notes (next update at)` | `internal comment (next update at)` | `Next update (date)` | `private note (next update at)` |
| `urgency` |  | `urgency` | `Urgency` | `Urgency (status)` | `urgency` |
| `assignment_group` |  | `assignment_group` | `Team` | `Team (people)` | `group_id` |
| `category` |  | `category` | `Request type` | `Category (status)` | `category` |
| `subcategory` |  | `subcategory` | `Components` | `Subcategory (dropdown)` | `sub_category` |
| `resolution` |  | `close_notes` | `Resolution` | `Resolution (long text)` | `resolution notes` |

### `task_item`

Use `parent_ref` to link follow-ups to the change or incident they came from.

| Field | Required | ServiceNow | Jira/JSM | monday | Freshservice |
|---|---|---|---|---|---|
| `title` | yes | `short_description` | `summary` | `subitem name` | `title` |
| `description` | yes | `description` | `description` | `update` | `description` |
| `assignee` | yes | `assigned_to` | `assignee` | `Owner (people)` | `agent_id` |
| `due` | yes | `due_date` | `duedate` | `Due date (date)` | `due_date` |
| `parent_ref` | yes | `parent` | `parent` | `parent item` | `parent ticket/change` |
| `priority` |  | `priority` | `priority` | `Priority (status)` | `priority` |
| `labels` |  | `sys_tags (label entries)` | `labels` | `Tags` | `tags` |
