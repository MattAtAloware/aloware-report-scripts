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

Follows the **Claude-orchestrates, Python-renders** pattern.

All SQL generation, batching, date resolution, data contract building, and HTML
rendering are handled by two Python scripts in `MattAtAloware/aloware-report-scripts`.
Claude's only job is: stage scripts via GitHub MCP → run scripts → pass SQL to
Metabase MCP → pass HTML to Gmail MCP.

**Claude never writes SQL, never builds JSON contracts, never generates HTML.**
The scripts are the single source of truth.

**Scripts repo:** `MattAtAloware/aloware-report-scripts` → `agent-status-report/`

| Script | Purpose |
|--------|--------|
| `run_report.py` | Orchestrator — setup, SQL generation, batching, rendering |
| `build_email.py` | HTML renderer — called by run_report.py internally |

**TEST_MODE:** ON by default — all emails draft to `matthew@aloware.com` with a
`[TEST]` subject prefix. User must say **"send live"** to disable.

---

## Inputs

| Input | Default | Example |
|-------|---------|--------|
| `company_id` | required | `6364` |
| `company_name` | required | `Debt Freedom USA` |
| `recipients` | required | `raul@client.com, edwin@client.com` |
| `start_date` | yesterday | `2026-04-06` |
| `end_date` | = start_date | `2026-04-10` |
| `test_mode` | `true` | say "send live" to set false |

---

## Execution — exactly 5 steps

### Step 0 — Load tools

Before anything else, load all MCP tool schemas in a single call:

```
ToolSearch("select:mcp__metabase__execute,mcp__c3f017eb-2a8d-48aa-ab10-03ecb2b2a2dd__gmail_create_draft,mcp__github__get_file_contents")
```

### Step 1 — Stage scripts and run setup (2 GitHub-MCP calls + 1 Bash + 1 Metabase)

**Do NOT use `curl` to fetch scripts from GitHub.** Sandboxed shells (Cowork)
consistently return 403 from `raw.githubusercontent.com`. Use the GitHub MCP
instead — it's already authenticated and never fails for these files.

Stage both scripts:

```
mcp__github__get_file_contents(
  owner: "MattAtAloware",
  repo: "aloware-report-scripts",
  path: "agent-status-report/run_report.py"
)
# Response includes "content" (base64). Decode and save to $WORK_DIR/run_report.py.

mcp__github__get_file_contents(
  owner: "MattAtAloware",
  repo: "aloware-report-scripts",
  path: "agent-status-report/build_email.py"
)
# Decode and save to $WORK_DIR/build_email.py.
```

Send these two calls in parallel. Then write both files into the work_dir
(use the file Write tool for the absolute path under your outputs folder so
the same path is visible to both bash and the Python subprocess) and run setup:

```bash
WORK_DIR="<path you just wrote both .py files into>"
python3 "$WORK_DIR/run_report.py" setup \
  --company-id {COMPANY_ID} \
  --company-name "{COMPANY_NAME}" \
  --start-date {START_DATE} \
  --end-date {END_DATE} \
  {--test-mode if applicable} \
  --work-dir "$WORK_DIR"
```

`run_report.py setup` will detect that `build_email.py` is already present in
`$WORK_DIR` and skip the network entirely (it falls back to api.github.com if
the file is missing — never raw.githubusercontent.com first).

Output is JSON. Extract `agent_list_query.sql` and execute it via Metabase MCP:

```
mcp__metabase__execute(
  database_id: 2,
  query: <sql from output>,
  row_limit: 500
)
```

If Metabase returns 0 rows → ABORT. Tell user "No agent activity found."
Save `work_dir` from the setup output — you need it for Step 3.

### Step 2 — Plan + Execute batches (1 Bash call + N Metabase calls)

Pass the user_ids from Step 1 to the plan command:

```bash
python3 "$WORK_DIR/run_report.py" plan \
  --company-id {COMPANY_ID} \
  --start-date {START_DATE} \
  --end-date {END_DATE} \
  --user-ids '{JSON_ARRAY_OF_USER_IDS}'
```

Output is JSON with a `queries` array. Execute each query via Metabase MCP:

```
for each query in queries:
  mcp__metabase__execute(
    database_id: query.database_id,
    query: query.sql,
    row_limit: query.row_limit
  )
```

**Accumulate ALL rows from ALL batches into a single JSON array.**

### Step 3 — Render (1 Bash call)

Pass accumulated rows to the render command:

```bash
python3 "$WORK_DIR/run_report.py" render \
  --company-id {COMPANY_ID} \
  --company-name "{COMPANY_NAME}" \
  --start-date {START_DATE} \
  --end-date {END_DATE} \
  {--test-mode if applicable} \
  --work-dir "$WORK_DIR" \
  --rows-json '{JSON_ARRAY_OF_ALL_ROWS}'
```

Output is JSON containing:
- `html_parts`: array of 1-2 HTML strings (pre-split if >18KB)
- `summary`: utilization_pct, top_performer, low_performers
- `email`: subject line (with [TEST] prefix if test_mode)
- `agent_count`, `date_label`

### Step 4 — Deliver via Gmail (1 Gmail call)

Concatenate `html_parts` and call `gmail_create_draft`:

```
gmail_create_draft(
  to: <recipients> (or matthew@aloware.com if test_mode),
  subject: email.subject_prefix + email.subject,
  body: html_parts[0] + html_parts[1] (if exists),
  contentType: "text/html"
)
```

### Step 5 — Confirm

Reply with: agent count, date, draft recipient(s), utilization %, top performer,
and TEST_MODE status. All stats come from the render output — do not parse HTML.

---

## Tool call budget

| Client size | Metabase batches | Total tool calls |
|-------------|-----------------|------------------|
| Small (≤60 agents) | 1 | 8 |
| Medium (61-120) | 2 | 9 |
| Large (121-180) | 3 | 10 |

Breakdown: ToolSearch(1) + GitHub-MCP-fetch×2 + Bash-setup(1) +
Metabase-agents(1) + Bash-plan(1) + Metabase-batches(N) + Bash-render(1) +
Gmail(1) = **8 + (N-1)** total calls.

(GitHub MCP calls can be sent in parallel, so wall time is unchanged from the
old curl-based flow.)

---

## Error handling

| Condition | Action |
|-----------|--------|
| GitHub MCP fetch fails | ABORT immediately. Do not attempt curl as fallback — it will 403. |
| Setup fails | Show stderr from output JSON. ABORT. |
| Step 1 returns 0 rows | Tell user, confirm company_id and date range |
| Render fails (non-zero exit) | Show stderr from output JSON. Do not improvise HTML. |
| Gmail fails | Show error. Ask user if they want to retry. |

---

## Critical rules

- **Never use curl to fetch scripts from GitHub.** Always use the GitHub MCP.
  raw.githubusercontent.com 403s in sandboxed shells.
- **Never write SQL.** run_report.py generates all SQL. Execute it verbatim.
- **Never build JSON contracts.** run_report.py builds the data contract internally.
- **Never generate HTML.** build_email.py renders it. run_report.py calls it.
- **Never use TodoWrite in automated/scheduled runs.** No user is watching.
- **Never call the Skill tool in scheduled runs.** Instructions are already provided.
- **Use a stable work_dir under your outputs folder, not /tmp.** Both bash and
  the Python subprocess need to see the same path; the file tools and bash see
  different roots, so an absolute path under `outputs/` is the safest pick.
- **database_id is 2.** Always.
- **TEST_MODE is on by default.** Never send live without explicit user confirmation.
- **Batch by 60 user_ids.** run_report.py handles this — just pass all user_ids.
- **Do not use subagents for delivery.** Always call Gmail from the main context.
