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

Follows the **Claude-orchestrates, Python-renders** pattern from `MattAtAloware/cowork-skill-template`.

1. Fetch renderer script from GitHub (Step 0 — before any data queries)
2. Gather data via Metabase (Steps 1–2)
3. Write data contract JSON (Step 3)
4. Run renderer → output HTML (Step 4)
5. Deliver via Gmail MCP (Step 5)

**Claude never generates report HTML directly.** The renderer is the source of truth.

**Scripts repo:** `MattAtAloware/aloware-report-scripts` → `agent-status-report/build_email.py`

**Working dir:** `/tmp/agent-status/` — create at start:
```bash
rm -rf /tmp/agent-status 2>/dev/null; mkdir -p /tmp/agent-status
```

**TEST_MODE:** ON by default — all emails draft to `matthew@aloware.com` with a `[TEST]` subject prefix and an in-email banner. User must say **"send live"** to disable.

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

**Date shortcuts** (resolve before querying):
- nothing / "yesterday" → yesterday / yesterday
- "last week" → last Mon / last Sun
- "this week" → this Mon / today
- "last 7 days" → 7 days ago / yesterday
- "last month" → 1st of prior month / last day of prior month

---

## Step 0 — Fetch renderer from GitHub

**Do this first, before any data queries.** If it fails, abort immediately.

The renderer is a pure-Python email-safe HTML generator — no JS, no `<style>` blocks,
all inline CSS. Output is ~20KB for 16 agents, ~30KB for 28 agents. Gmail-compatible.

```python
import base64

result = mcp__github__get_file_contents(
    owner="MattAtAloware",
    repo="aloware-report-scripts",
    path="agent-status-report/build_email.py"
)
content = base64.b64decode(result["content"]).decode("utf-8")
open("/tmp/agent-status/build_email.py", "w").write(content)
```

| Condition | Action |
|-----------|--------|
| Fetch succeeds | Continue to Step 1 |
| 404 or any error | **ABORT.** Tell user: "Could not fetch the renderer from GitHub." |

---

## Step 1 — Fetch agent list

```sql
SELECT DISTINCT aa.user_id
FROM aloware.agent_audits aa
WHERE aa.company_id = {COMPANY_ID}
  AND aa.property   = 'agent_status'
  AND aa.created_at >= '{START_DATE} 00:00:00'
  AND aa.created_at <  '{END_DATE_EXCLUSIVE} 00:00:00'
ORDER BY aa.user_id
```

`database_id: 2`, `row_limit: 500`. Collect all user_ids.

If 0 rows: tell user "No agent activity found for this company/date range." Do not proceed.

---

## Step 2 — Query status data in batches of 60

**Why batches:** `metabase_execute` silently truncates at 500 rows. Large clients have
200+ agents × 7 statuses = 1,400+ rows/day. Batch by 60 user_ids (= 420 rows max per
call). Run the query below once per batch, accumulate all rows — the renderer handles
final aggregation, so pass the full raw unmerged list.

**How duration is calculated — LEAD() with explicit midnight cap, not SUM(duration):**

The `duration` column in `agent_audits` stores how long the agent was in the *previous*
(from) status before transitioning — **not** the current status. It can represent days of
accumulated time if an agent hasn't logged in recently and is completely unreliable for
daily reports.

Instead, use `LEAD()` to compute actual wall-clock time between consecutive transitions:
- Use `"to"` as the status key (the status the agent *entered*)
- Cap trailing active statuses at `{END_DATE_EXCLUSIVE} 00:00:00` (midnight) — this
  gives the agent credit for time up to end of day without bleeding into tomorrow
- When `next_at IS NULL AND status_code = '0'` (trailing offline), set `ended_at =
  started_at` so the `WHERE ended_at > started_at` filter removes it — this prevents
  phantom offline hours for agents who logged off before midnight
- Use `DATEDIFF('second', started_at, ended_at)` for clean, readable duration math

`{BATCH_USER_IDS}` = comma-separated ids from current batch, e.g. `123,456,789`
`{END_DATE_EXCLUSIVE}` = day after end_date

```sql
WITH transitions AS (
  SELECT
    aa.user_id,
    (u.first_name || ' ' || u.last_name)  AS agent_name,
    aa."to"                                AS status_code,
    aa.created_at                          AS started_at,
    LEAD(aa.created_at) OVER (
      PARTITION BY aa.user_id
      ORDER BY aa.created_at
    )                                      AS next_at
  FROM aloware.agent_audits aa
  JOIN aloware.users u ON u.id = aa.user_id
  WHERE aa.company_id = {COMPANY_ID}
    AND aa.user_id    IN ({BATCH_USER_IDS})
    AND aa.property   = 'agent_status'
    AND aa.created_at >= '{START_DATE} 00:00:00'
    AND aa.created_at <  '{END_DATE_EXCLUSIVE} 00:00:00'
    AND aa."to"       IN ('0','1','2','3','4','5','6')
),
capped AS (
  SELECT
    agent_name,
    status_code,
    started_at,
    CASE
      WHEN next_at IS NOT NULL THEN next_at
      WHEN status_code = '0'   THEN started_at
      ELSE '{END_DATE_EXCLUSIVE} 00:00:00'
    END AS ended_at
  FROM transitions
)
SELECT
  agent_name,
  status_code,
  SUM(DATEDIFF('second', started_at, ended_at)) AS total_seconds
FROM capped
WHERE ended_at > started_at
GROUP BY agent_name, status_code
ORDER BY agent_name, status_code
```

`database_id: 2`, `row_limit: 500`.

**Status codes:** 0=Offline 1=Available 2=Busy 3=On Break 4=On Call 5=Wrap-Up 6=Ringing

**Note on legacy data:** Some rows contain non-numeric values in `"to"` (e.g. `"offline"`
from older app versions). The `IN ('0',...,'6')` filter excludes these automatically.

---

## Step 3 — Write data contract JSON

After all batches complete, write `/tmp/agent-status/report_data.json`.
This is the only interface between Claude and the renderer — no other data passing.

```python
import json
from datetime import datetime

test_mode = True  # flip to False only if user said "send live"

contract = {
    "meta": {
        "skill_name": "agent-status-time-report",
        "company_name": company_name,
        "company_id": company_id,
        "date_range": {"start": start_date, "end": end_date},
        "output_format": "email",
        "test_mode": test_mode,
        "generated_at": datetime.now().isoformat()
    },
    "rows": all_accumulated_rows   # raw list across all batches — renderer aggregates internally
}

with open("/tmp/agent-status/report_data.json", "w") as f:
    json.dump(contract, f)
```

Each row: `{"agent_name": "Ana Cruz", "status_code": "1", "total_seconds": 8435}`

---

## Step 4 — Run renderer

The renderer is pure Python — **no pip installs needed**. No matplotlib, no PIL, no
external dependencies. It generates email-safe HTML with all inline CSS, no JavaScript.

```bash
python /tmp/agent-status/build_email.py \
  --input /tmp/agent-status/report_data.json \
  --out   /tmp/agent-status/output.html
```

| Condition | Action |
|-----------|--------|
| Exits 0, output.html exists | Continue |
| Exits non-zero | Show full traceback. Do not improvise HTML. |
| output.html missing | ABORT. |

---

## Step 5 — Deliver via Gmail MCP

**CRITICAL: Do NOT use a subagent for delivery.** Subagents truncate or improvise HTML
when the body is large. Instead, read the HTML directly and call `gmail_create_draft`
from the main context.

**For files ≤20KB (~16 agents):** Read the file directly with the Read tool, then pass
the full contents to `gmail_create_draft`.

**For files >20KB (~28+ agents):** The Read tool has a 10,000-token limit. Split the
HTML into two parts using Python:

```python
html = open('/tmp/agent-status/output.html').read()
mid = len(html) // 2
split_point = html.index('</tr>', mid) + len('</tr>')
open('/tmp/agent-status/part1.html', 'w').write(html[:split_point])
open('/tmp/agent-status/part2.html', 'w').write(html[split_point:])
```

Read both parts, then concatenate when calling `gmail_create_draft`.

```
Call gmail_create_draft with:
  to          = "matthew@aloware.com" (test_mode=true) OR <recipients> (live)
  subject     = "[TEST] Agent Status Time Report – {company} – {date_label}" (test_mode=true)
                OR "Agent Status Time Report – {company} – {date_label}" (live)
  body        = <full HTML contents — part1 + part2, must start with <!DOCTYPE html>>
  contentType = "text/html"   ← camelCase, critical
```

---

## Step 6 — Confirm

Reply with: agent count, date range, draft recipient(s), and whether TEST_MODE was active.

---

## Error handling

| Condition | Action |
|-----------|--------|
| GitHub renderer fetch fails | **ABORT immediately** |
| Step 1 returns 0 rows | Tell user, confirm company_id and date range, stop |
| Build script exits non-zero | Show traceback. Do not freestyle HTML. |
| `gmail_create_draft` fails | Show error. Ask user if they want to retry. |

---

## Critical rules

- **Use LEAD() on `"to"`, not `SUM(duration)` on `"from"`** — the `duration` column stores
  time in the *previous* status and can represent days of accumulated time. LEAD() computes
  actual wall-clock time between consecutive transitions, which is the only correct approach.
- **Cap trailing active statuses at midnight** — when `next_at IS NULL` and status is not
  Offline, set `ended_at = '{END_DATE_EXCLUSIVE} 00:00:00'`. This gives credit for the
  remaining shift without bleeding into tomorrow.
- **Strip trailing offline** — when the last event is going Offline (status 0) and
  `next_at IS NULL`, set `ended_at = started_at` so the `WHERE ended_at > started_at`
  filter removes it. This prevents phantom offline hours for agents who logged off before midnight.
- **Use `DATEDIFF('second', started_at, ended_at)`** — cleaner and more readable than
  `EXTRACT(EPOCH FROM ...)` for duration math.
- **Filter `"to" IN ('0',...,'6')`** — legacy rows may have string values like `"offline"`
  which must be excluded or they inflate the wrong bucket.
- **Always batch by 60 user_ids** — 200-agent clients = 1,400 rows/day, silent truncation at 500.
- **No activity found?** Don't send. Tell the user and confirm the date/company_id before retrying.
- **database_id is 2.** Do not use saved card 2477 — permission errors.
- **TEST_MODE is always on by default.** Never send live without explicit user confirmation.
- **No pip installs needed.** The renderer has zero external dependencies.
- **Never use a subagent to deliver email.** Subagents truncate large HTML bodies or
  improvise their own HTML. Always read the file directly and call `gmail_create_draft`
  from the main context. For files >20KB, split into two parts first.
- **Gmail strips JavaScript.** The renderer must produce email-safe HTML — no `<script>`,
  no `<style>` blocks, all CSS inline. Table-based layout only.
