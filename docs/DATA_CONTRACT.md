# Data Contract — agent-status-time-report

This document is the authoritative schema for `report_data.json` — the file written by the `agent-status-time-report` skill and read by `build_email.py`.

## File Location

```
/tmp/agent-status/report_data.json
```

## Top-Level Structure

```json
{
  "meta": { ... },
  "rows": [ ... ]
}
```

## `meta` Object

| Field | Type | Required | Description |
|---|---|---|---|
| `skill_name` | string | ✓ | Always `"agent-status-time-report"` |
| `company_name` | string | ✓ | Display name of the client company |
| `company_id` | integer | ✓ | Aloware `companies.id` |
| `recipients` | string | ✓ | Comma-separated recipient email addresses |
| `date_range` | object | ✓ | `{ "start": "YYYY-MM-DD", "end": "YYYY-MM-DD" }` |
| `output_format` | string | ✓ | Always `"email"` for this renderer |
| `test_mode` | boolean | ✓ | `true` = draft to matthew@aloware.com; `false` = draft to `recipients` |
| `generated_at` | string | ✓ | ISO 8601 timestamp of contract creation |

**`test_mode` must be a strict JSON boolean** (`true` or `false`). String `"true"`, integer `1`, or `null` must be rejected by the consuming skill before the contract is written.

## `rows` Array

Each element represents one agent × status code aggregation for the reporting period.

| Field | Type | Required | Description |
|---|---|---|---|
| `agent_name` | string | ✓ | `first_name + ' ' + last_name` from `aloware.users` |
| `status_code` | string | ✓ | See status code table below |
| `total_seconds` | number | ✓ | Total seconds spent in this status. Must be ≥ 0. |

### Status Code Reference

| Code | Label | Color (for renderers) |
|---|---|---|
| `"0"` | Offline | Gray |
| `"1"` | Available | Green |
| `"2"` | Busy | Orange |
| `"3"` | On Break | Yellow |
| `"4"` | On Call | Blue |
| `"5"` | Wrap-Up | Purple |
| `"6"` | Ringing | Teal |

## Validation Rules

The consuming skill validates the contract immediately after writing it. A contract that fails any of these rules is rejected — the renderer is never invoked:

1. File must be valid JSON (parseable without error)
2. All required `meta` fields must be present
3. `test_mode` must be strict boolean `true` or `false`
4. `rows` must be a non-empty list
5. Every row must contain `agent_name`, `status_code`, and `total_seconds`
6. `total_seconds` must be a non-negative number

## Example

```json
{
  "meta": {
    "skill_name": "agent-status-time-report",
    "company_name": "Debt Freedom USA",
    "company_id": 6364,
    "recipients": "raul@debtfreedomusa.com, edwin@debtfreedomusa.com",
    "date_range": { "start": "2026-04-07", "end": "2026-04-13" },
    "output_format": "email",
    "test_mode": true,
    "generated_at": "2026-04-13T10:32:00.000000"
  },
  "rows": [
    { "agent_name": "Ana Cruz",   "status_code": "1", "total_seconds": 8435 },
    { "agent_name": "Ana Cruz",   "status_code": "2", "total_seconds": 1200 },
    { "agent_name": "Ana Cruz",   "status_code": "4", "total_seconds": 5400 },
    { "agent_name": "Bob Torres", "status_code": "1", "total_seconds": 7200 },
    { "agent_name": "Bob Torres", "status_code": "0", "total_seconds": 3600 }
  ]
}
```

## Renderer Output Contract

The renderer (`build_email.py`) must:

- Exit `0` only if a valid HTML file was written to `--out`
- Exit `1` with a stderr message if any input is invalid or rendering fails
- Output must start with `<!DOCTYPE html>`
- Output size must be 10 KB – 512 KB
- All dynamic values must be HTML-escaped before template injection (XSS prevention)
- No hardcoded company names, email addresses, or client IDs
