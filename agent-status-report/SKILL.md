---
name: agent-status-time-report
description: >
  Generates an Agent Status Time Report for any Aloware client. Queries agent
  status transitions from the Aloware production database, builds an email-safe
  HTML report (KPI cards, color-coded agent table), and sends it to the specified
  recipients as an inline HTML email — no attachments, no JavaScript.
  Use when someone asks for an agent status report, time-in-status report, agent
  activity report, how long agents spent in each status, or wants a daily/weekly
  status summary emailed to a client. Triggers on: "send the agent status report for
  client X", "generate the status report for [company]", "email [client] their agent
  time report", or any variation involving a company_id + recipients + status/activity.
---

# Agent Status Time Report

## Architecture

**Claude-orchestrates, Python-owns-SQL** pattern.

The SQL, batching logic, and data contract format all live in `query_report.py` —
not in this skill. Claude never writes or interprets SQL. It fetches the scripts,
runs them with parameters, and delivers the output.

**Pipeline:**

1. Fetch scripts from GitHub (Step 0)
2. Run `query_report.py generate-sql --agent-list-only` → get agent-list SQL
3. Execute agent-list SQL via Metabase MCP → get user_ids
4. Run `query_report.py generate-sql --user-ids '[...]'` → get batch SQL queries
5. Execute each batch SQL via Metabase MCP → accumulate rows
6. Write rows to `/tmp/agent-status/rows.json`
7. Run `query_report.py build-contract` → writes `report_data.json`
8. Run `build_email.py --chart-dir` → renders `output.html` + chart JPEGs
9. Upload chart JPEGs to GitHub → get raw URLs
10. Replace chart URL placeholders in HTML
11. Deliver via Gmail MCP

**Scripts repo:** `MattAtAloware/aloware-report-scripts` → `agent-status-report/`

**Working dir:** `/tmp/agent-status/` — create fresh at start:
```bash
rm -rf /tmp/agent-status 2>/dev/null; mkdir -p /tmp/agent-status
```

**TEST_MODE:** ON by default — all emails draft to `matthew@aloware.com` with a `[TEST]`
subject prefix. User must say **"send live"** to disable.

---

## Inputs

| Input | Default | Example |
|-------|---------|---------|
| `company_id` | required | `6364` |
| `company_name` | required | `Debt Freedom USA` |
| `recipients` | required | `raul@client.com, edwin@client.com` |
| `start_date` | yesterday | `2026-04-06` |
| `end_date` | = start_date | `2026-04-10` |
| `test_mode` | `true` | say "send live" to set false |

**Date shortcuts** (pass directly to `query_report.py --start-date`):
`yesterday`, `last week`, `this week`, `last 7 days`, `last month`, or `YYYY-MM-DD`

---

## Step 0 — Fetch scripts from GitHub

**Do this first.** Fetch both scripts in parallel. If either fails, abort immediately.

```python
import base64

# Fetch query_report.py
r1 = mcp__github__get_file_contents(
    owner="MattAtAloware", repo="aloware-report-scripts",
    path="agent-status-report/query_report.py"
)
open("/tmp/agent-status/query_report.py", "w").write(
    base64.b64decode(r1["content"]).decode("utf-8")
)

# Fetch build_email.py
r2 = mcp__github__get_file_contents(
    owner="MattAtAloware", repo="aloware-report-scripts",
    path="agent-status-report/build_email.py"
)
open("/tmp/agent-status/build_email.py", "w").write(
    base64.b64decode(r2["content"]).decode("utf-8")
)
```

| Condition | Action |
|-----------|--------|
| Both fetched | Continue |
| Either fails | **ABORT.** Tell user which script could not be fetched. |

---

## Step 1 — Get agent-list SQL from script

```bash
python /tmp/agent-status/query_report.py generate-sql \
  --company-id {COMPANY_ID} \
  --start-date "{START_DATE}" \
  --end-date   "{END_DATE}" \
  --agent-list-only
```

This prints a JSON object. Extract the `"sql"` field. That is the exact SQL to run next.
Also capture `"start_date"`, `"end_date"`, `"end_date_exclusive"` from the output —
use these values for all subsequent steps (they are the resolved dates).

---

## Step 2 — Execute agent-list SQL via Metabase

Run the SQL from Step 1 verbatim:
- `database_id: 2`
- `row_limit: 500`

Collect all `user_id` values from the result rows into a JSON array: `[id1, id2, ...]`

If 0 rows: tell user "No agent activity found for this company/date range." Stop.

---

## Step 3 — Get batch SQL queries from script

```bash
python /tmp/agent-status/query_report.py generate-sql \
  --company-id {COMPANY_ID} \
  --start-date "{START_DATE}" \
  --end-date   "{END_DATE}" \
  --user-ids   '{USER_IDS_JSON_ARRAY}'
```

This prints a JSON object with a `"queries"` array. Each element has:
- `"sql"` — the exact SQL to run
- `"database_id"` — always 2
- `"row_limit"` — always 500
- `"batch"` / `"total_batches"` — for progress tracking

---

## Step 4 — Execute batch SQL queries via Metabase

Run each query from Step 3 verbatim against Metabase (`database_id: 2`, `row_limit: 500`).
Accumulate all result rows across all batches into a single list.

Each row has: `agent_name`, `status_code`, `total_seconds`.

Write the accumulated rows to `/tmp/agent-status/rows.json`:
```python
import json
json.dump(all_rows, open("/tmp/agent-status/rows.json", "w"))
```

---

## Step 5 — Build data contract

```bash
python /tmp/agent-status/query_report.py build-contract \
  --company-id   {COMPANY_ID} \
  --company-name "{COMPANY_NAME}" \
  --start-date   "{START_DATE}" \
  --end-date     "{END_DATE}" \
  --rows-json    /tmp/agent-status/rows.json \
  --out          /tmp/agent-status/report_data.json \
  {--test-mode if test_mode else ""}
```

| Condition | Action |
|-----------|--------|
| Exits 0 | Continue |
| Exits non-zero | Show error. Do not proceed. |

---

## Step 6 — Run renderer with external charts

Run `build_email.py` with `--chart-dir` to save chart images as separate files
instead of embedding them as base64. The HTML will contain `{{BAR_CHART_URL}}`
and `{{DONUT_CHART_URL}}` placeholders where the chart images belong.

```bash
python /tmp/agent-status/build_email.py \
  --input     /tmp/agent-status/report_data.json \
  --out       /tmp/agent-status/output.html \
  --chart-dir /tmp/agent-status/charts
```

This produces:
- `/tmp/agent-status/output.html` — HTML with URL placeholders (~24-46KB, no base64)
- `/tmp/agent-status/charts/bar_chart.jpg` — stacked bar chart (~25-62KB)
- `/tmp/agent-status/charts/donut_chart.jpg` — donut chart (~7-8KB)

| Condition | Action |
|-----------|--------|
| Exits 0, all 3 files exist | Continue |
| Exits non-zero | Show full traceback. Do not improvise HTML. |
| Any file missing | ABORT. |

---

## Step 7 — Upload charts to GitHub and replace placeholders

### 7a. Upload chart images to GitHub

Upload both chart JPEGs to the repo using `create_or_update_file`. The content
must be the raw file bytes encoded as base64.

**Path convention:** `agent-status-report/charts/{company_id}_{date_label}/bar_chart.jpg`

Where `date_label` is:
- Single day: `2026-04-13`
- Date range: `2026-04-07_to_2026-04-13`

```python
import base64

date_label = start_date if start_date == end_date else f"{start_date}_to_{end_date}"
chart_path_prefix = f"agent-status-report/charts/{company_id}_{date_label}"

bar_b64 = base64.b64encode(open("/tmp/agent-status/charts/bar_chart.jpg", "rb").read()).decode()
donut_b64 = base64.b64encode(open("/tmp/agent-status/charts/donut_chart.jpg", "rb").read()).decode()
```

Upload both via `mcp__github__create_or_update_file`:
- `owner`: `MattAtAloware`
- `repo`: `aloware-report-scripts`
- `branch`: `main`
- `path`: `{chart_path_prefix}/bar_chart.jpg` and `{chart_path_prefix}/donut_chart.jpg`
- `content`: the base64 string of the raw JPEG bytes
- `message`: `Upload charts for {company_name} {date_label}`

**If updating existing charts** (re-running a report for the same date), you must
include the `sha` of the existing file. Use `get_file_contents` first to check,
or handle the 422 error by fetching the SHA and retrying.

### 7b. Build raw URLs

```
bar_url   = https://raw.githubusercontent.com/MattAtAloware/aloware-report-scripts/main/{chart_path_prefix}/bar_chart.jpg
donut_url = https://raw.githubusercontent.com/MattAtAloware/aloware-report-scripts/main/{chart_path_prefix}/donut_chart.jpg
```

### 7c. Replace placeholders in HTML

```python
html = open("/tmp/agent-status/output.html").read()
html = html.replace("{{BAR_CHART_URL}}", bar_url)
html = html.replace("{{DONUT_CHART_URL}}", donut_url)
open("/tmp/agent-status/output_final.html", "w").write(html)
```

---

## Step 8 — Deliver via Gmail MCP

**CRITICAL: Do NOT use a subagent for delivery.** Subagents truncate or improvise HTML.
Always read the file directly and call `gmail_create_draft` from the main context.

**With external charts, the HTML is ~24-46KB** (no base64 image data). Most reports
(≤20 agents) will be under the Read tool's token limit.

**If the file exceeds the Read tool limit** (28+ agents, ~46KB), split at a `</tr>`
boundary:
```python
html = open('/tmp/agent-status/output_final.html').read()
mid = len(html) // 2
split_point = html.index('</tr>', mid) + len('</tr>')
open('/tmp/agent-status/part1.html', 'w').write(html[:split_point])
open('/tmp/agent-status/part2.html', 'w').write(html[split_point:])
```
Read both parts and concatenate when calling `gmail_create_draft`.

```
Call gmail_create_draft with:
  to          = "matthew@aloware.com" (test_mode=true) OR <recipients> (live)
  subject     = "[TEST] Agent Status Time Report – {company} – {date_label}" (test_mode=true)
                OR "Agent Status Time Report – {company} – {date_label}" (live)
  body        = <full HTML contents — must start with <!DOCTYPE html>>
  contentType = "text/html"   ← camelCase, critical
```

---

## Step 9 — Confirm

Reply with: agent count, date range, draft recipient(s), and whether TEST_MODE was active.

---

## Error handling

| Condition | Action |
|-----------|--------|
| GitHub script fetch fails | **ABORT immediately** |
| Step 2 returns 0 rows | Tell user, confirm company_id and date range, stop |
| query_report.py exits non-zero | Show error output. Do not freestyle. |
| build_email.py exits non-zero | Show full traceback. Do not improvise HTML. |
| Chart upload to GitHub fails | Show error. Retry once. If still failing, abort. |
| `gmail_create_draft` fails | Show error. Ask user if they want to retry. |

---

## Critical rules

- **SQL lives in `query_report.py`, not here.** Never write SQL inline. Always get it
  from the script's `generate-sql` command and execute it verbatim.
- **Always batch.** `query_report.py` handles batch sizing (60 user_ids). Don't override it.
- **Always use `--chart-dir` when rendering.** This saves charts as separate files and
  uses URL placeholders in the HTML. Never use inline base64 — Gmail strips embedded
  images, and base64 bloats the HTML beyond the Read tool's token limit.
- **Upload charts to GitHub before delivering.** The HTML contains `{{BAR_CHART_URL}}`
  and `{{DONUT_CHART_URL}}` placeholders that MUST be replaced with live
  `raw.githubusercontent.com` URLs before sending.
- **Never strip base64 from the HTML.** The old `re.sub(r'src="data:image/..."')` approach
  is obsolete. Charts are now externally hosted.
- **No activity found?** Don't send. Tell the user and confirm the date/company_id.
- **database_id is 2.** Never use saved cards — permission errors.
- **TEST_MODE is always on by default.** Never send live without explicit user confirmation.
- **No pip installs needed.** Both scripts have zero external dependencies beyond matplotlib/PIL
  (already installed in the sandbox).
- **Never use a subagent to deliver email.** Always call `gmail_create_draft` from main context.
- **Gmail strips JavaScript.** The renderer produces email-safe HTML — no `<script>`,
  no `<style>` blocks, all CSS inline. Table-based layout only.
