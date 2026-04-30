#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_report.py — Agent Status Time Report: single-script orchestrator.

Owns the ENTIRE pipeline except Metabase queries and Gmail delivery,
which must go through MCP tools that only Claude can call.

THREE MODES (called sequentially by Claude):

  1. setup
     Downloads build_email.py from GitHub, resolves dates, prints the
     agent-list SQL for Claude to execute via Metabase MCP.
     Output: JSON with setup metadata + SQL to run.

  2. plan
     Accepts the agent-list query results (user_ids), generates batched
     status SQL queries for Claude to execute via Metabase MCP.
     Output: JSON array of SQL queries with metadata.

  3. render
     Accepts accumulated Metabase rows, builds data contract, runs the
     renderer, and outputs the final HTML (or split parts if >20KB).
     Output: JSON with html_parts array and email metadata.

This eliminates all improvisation. Claude's job is reduced to:
  - Call run_report.py setup → get SQL → call Metabase
  - Call run_report.py plan → get SQL(s) → call Metabase per batch
  - Call run_report.py render → get HTML + metadata → call Gmail

Zero pip installs. Zero external dependencies. Pure stdlib.
"""

import argparse
import base64
import json
import os
import sys
import tempfile
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE = 60
DATABASE_ID = 2
# GitHub API (base64-encoded). The raw URL (raw.githubusercontent.com) is NOT
# used as a fallback — it 403s reliably in Cowork's sandboxed shell, so keeping
# it would just add latency and mislead error messages.
GITHUB_API_URL = (
    "https://api.github.com/repos/MattAtAloware/"
    "aloware-report-scripts/contents/agent-status-report/build_email.py"
)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def resolve_dates(start_arg: str, end_arg: str = None) -> tuple:
    """Resolve date shortcut strings to (start_date, end_date) YYYY-MM-DD."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    if not start_arg or start_arg == "yesterday":
        return str(yesterday), str(yesterday)
    if start_arg == "today":
        return str(today), str(today)
    if start_arg == "last week":
        days_since_mon = today.weekday()
        last_mon = today - timedelta(days=days_since_mon + 7)
        last_sun = last_mon + timedelta(days=6)
        return str(last_mon), str(last_sun)
    if start_arg == "this week":
        days_since_mon = today.weekday()
        this_mon = today - timedelta(days=days_since_mon)
        return str(this_mon), str(today)
    if start_arg == "last 7 days":
        return str(today - timedelta(days=7)), str(yesterday)
    if start_arg == "last month":
        first_of_this = today.replace(day=1)
        last_of_prev = first_of_this - timedelta(days=1)
        first_of_prev = last_of_prev.replace(day=1)
        return str(first_of_prev), str(last_of_prev)

    end = end_arg if end_arg else start_arg
    return start_arg, end


def end_date_exclusive(end_date_str: str) -> str:
    d = datetime.strptime(end_date_str, "%Y-%m-%d")
    return (d + timedelta(days=1)).strftime("%Y-%m-%d")


def format_date_label(start_str: str, end_str: str = None) -> str:
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d")
        if not end_str or end_str == start_str:
            return start.strftime("%B %-d, %Y")
        end = datetime.strptime(end_str, "%Y-%m-%d")
        if start.year != end.year:
            return f"{start.strftime('%B %-d, %Y')} - {end.strftime('%B %-d, %Y')}"
        if start.month != end.month:
            return f"{start.strftime('%B %-d')} - {end.strftime('%B %-d, %Y')}"
        return f"{start.strftime('%B %-d')}-{end.strftime('%-d, %Y')}"
    except Exception:
        return end_str or start_str


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------

def agent_list_sql(company_id: int, start_date: str, end_excl: str) -> str:
    return f"""SELECT DISTINCT aa.user_id
FROM aloware.agent_audits aa
WHERE aa.company_id = {company_id}
  AND aa.property   = 'agent_status'
  AND aa.created_at >= '{start_date} 00:00:00'
  AND aa.created_at <  '{end_excl} 00:00:00'
ORDER BY aa.user_id"""


def status_batch_sql(
    company_id: int,
    user_ids: list,
    start_date: str,
    end_excl: str,
) -> str:
    """
    Build status-duration SQL for a batch of user_ids.

    Uses the combined dedup+filter approach:
    - DISTINCT inside the deduped CTE collapses exact duplicate rows before
      LEAD() runs, preventing phantom zero-second segments that inflate total_s.
    - The IN ('0'..'6') filter inside deduped excludes legacy string statuses
      (e.g. "to"='offline') before they enter the transition chain, preventing
      them from consuming time from adjacent real-status rows.

    This is more accurate than filter-only (leaves duplicate rows) or dedup-only
    (lets legacy strings corrupt the transition chain).
    """
    batch_ids = ", ".join(str(uid) for uid in user_ids)
    return f"""WITH deduped AS (
  SELECT DISTINCT
    aa.user_id,
    aa."to"        AS status_code,
    aa.created_at
  FROM aloware.agent_audits aa
  WHERE aa.company_id = {company_id}
    AND aa.user_id    IN ({batch_ids})
    AND aa.property   = 'agent_status'
    AND aa.created_at >= '{start_date} 00:00:00'
    AND aa.created_at <  '{end_excl} 00:00:00'
    AND aa."to"       IN ('0','1','2','3','4','5','6')
),
transitions AS (
  SELECT
    d.user_id,
    (u.first_name || ' ' || u.last_name) AS agent_name,
    d.status_code,
    d.created_at                          AS started_at,
    LEAD(d.created_at) OVER (
      PARTITION BY d.user_id, DATE(d.created_at)
      ORDER BY d.created_at
    )                                     AS next_at
  FROM deduped d
  JOIN aloware.users u ON u.id = d.user_id
),
with_duration AS (
  SELECT
    agent_name,
    status_code,
    CASE
      WHEN next_at IS NULL AND status_code = '0' THEN 0
      WHEN next_at IS NULL THEN EXTRACT(EPOCH FROM (DATE_TRUNC('day', started_at) + INTERVAL '1 day' - started_at))
      ELSE EXTRACT(EPOCH FROM (next_at - started_at))
    END AS duration_secs
  FROM transitions
)
SELECT
  agent_name,
  status_code,
  SUM(duration_secs)::int AS total_seconds
FROM with_duration
WHERE duration_secs >= 0
GROUP BY agent_name, status_code
ORDER BY agent_name, status_code"""


# ---------------------------------------------------------------------------
# GitHub fetch
# ---------------------------------------------------------------------------

def fetch_renderer(work_dir: str) -> str:
    """Download build_email.py to work_dir. Returns path on success.

    Order of attempts:
      0. If file is already present in work_dir (pre-staged via GitHub MCP from
         SKILL.md), reuse it. No network needed. THIS IS THE EXPECTED PATH.
      1. GitHub API (api.github.com). Used only when SKILL.md didn't pre-stage
         the file. The raw URL (raw.githubusercontent.com) is intentionally NOT
         attempted — it 403s in Cowork's sandboxed shell.
    """
    dest = os.path.join(work_dir, "build_email.py")

    # 0. Pre-staged file (preferred path for sandboxed environments)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest

    # 1. GitHub API (base64) — only network attempt
    try:
        req = urllib.request.Request(GITHUB_API_URL)
        req.add_header("User-Agent", "aloware-run-report/1.0")
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        content = base64.b64decode(data["content"]).decode("utf-8")
        with open(dest, "w") as f:
            f.write(content)
        return dest
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Mode: setup
# ---------------------------------------------------------------------------

def cmd_setup(args):
    """Set up working directory, fetch renderer, resolve dates, emit agent-list SQL."""
    work_dir = args.work_dir or tempfile.mkdtemp(prefix="agent-status-")
    os.makedirs(work_dir, exist_ok=True)

    start_date, end_date = resolve_dates(args.start_date, args.end_date)
    end_excl = end_date_exclusive(end_date)
    date_label = format_date_label(start_date, end_date)

    # Fetch renderer
    renderer_path = fetch_renderer(work_dir)
    if not renderer_path:
        print(json.dumps({
            "status": "error",
            "error": "Failed to fetch build_email.py from GitHub. ABORT. "
                     "Tip: pre-stage build_email.py in work_dir via the GitHub "
                     "MCP (mcp__github__get_file_contents) before calling setup."
        }))
        sys.exit(1)

    sql = agent_list_sql(args.company_id, start_date, end_excl)

    output = {
        "status": "ok",
        "step": "setup",
        "work_dir": work_dir,
        "renderer_path": renderer_path,
        "company_id": args.company_id,
        "company_name": args.company_name,
        "start_date": start_date,
        "end_date": end_date,
        "end_date_exclusive": end_excl,
        "date_label": date_label,
        "test_mode": args.test_mode,
        "agent_list_query": {
            "database_id": DATABASE_ID,
            "row_limit": 500,
            "sql": sql,
        },
    }
    print(json.dumps(output))


# ---------------------------------------------------------------------------
# Mode: plan
# ---------------------------------------------------------------------------

def cmd_plan(args):
    """Accept user_ids JSON, emit batched status SQL queries."""
    try:
        user_ids = json.loads(args.user_ids)
    except json.JSONDecodeError:
        print(json.dumps({"status": "error", "error": "Invalid --user-ids JSON"}))
        sys.exit(1)

    if not user_ids:
        print(json.dumps({
            "status": "empty",
            "message": "No agents found. Do not send a report.",
        }))
        sys.exit(0)

    start_date, end_date = resolve_dates(args.start_date, args.end_date)
    end_excl = end_date_exclusive(end_date)

    batches = [user_ids[i:i + BATCH_SIZE] for i in range(0, len(user_ids), BATCH_SIZE)]
    queries = []
    for idx, batch in enumerate(batches, 1):
        sql = status_batch_sql(args.company_id, batch, start_date, end_excl)
        queries.append({
            "batch": idx,
            "total_batches": len(batches),
            "agent_count": len(batch),
            "database_id": DATABASE_ID,
            "row_limit": 500,
            "sql": sql,
        })

    output = {
        "status": "ok",
        "step": "plan",
        "total_agents": len(user_ids),
        "total_batches": len(batches),
        "queries": queries,
    }
    print(json.dumps(output))


# ---------------------------------------------------------------------------
# Mode: render
# ---------------------------------------------------------------------------

def cmd_render(args):
    """Accept accumulated rows, build contract, run renderer, output HTML parts."""
    work_dir = args.work_dir
    if not work_dir or not os.path.isdir(work_dir):
        print(json.dumps({"status": "error", "error": f"work_dir not found: {work_dir}"}))
        sys.exit(1)

    renderer_path = os.path.join(work_dir, "build_email.py")
    if not os.path.exists(renderer_path):
        print(json.dumps({"status": "error", "error": "build_email.py not found in work_dir"}))
        sys.exit(1)

    # Load rows
    try:
        rows = json.loads(args.rows_json)
    except json.JSONDecodeError:
        print(json.dumps({"status": "error", "error": "Invalid --rows-json"}))
        sys.exit(1)

    if not rows:
        print(json.dumps({"status": "empty", "message": "No rows to render."}))
        sys.exit(0)

    start_date, end_date = resolve_dates(args.start_date, args.end_date)
    date_label = format_date_label(start_date, end_date)

    # Normalize rows
    clean_rows = []
    for r in rows:
        try:
            clean_rows.append({
                "agent_name": str(r.get("agent_name", "Unknown")),
                "status_code": str(r.get("status_code", "0")),
                "total_seconds": int(r.get("total_seconds", 0) or 0),
            })
        except (TypeError, ValueError):
            continue

    # Write data contract
    contract_path = os.path.join(work_dir, "report_data.json")
    contract = {
        "meta": {
            "skill_name": "agent-status-time-report",
            "company_name": args.company_name,
            "company_id": args.company_id,
            "date_range": {"start": start_date, "end": end_date},
            "output_format": "email",
            "test_mode": args.test_mode,
            "generated_at": datetime.now().isoformat(),
        },
        "rows": clean_rows,
    }
    with open(contract_path, "w") as f:
        json.dump(contract, f)

    # Run renderer
    output_path = os.path.join(work_dir, "output.html")
    import subprocess
    result = subprocess.run(
        [sys.executable, renderer_path, "--input", contract_path, "--out", output_path],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(json.dumps({
            "status": "error",
            "error": "Renderer failed",
            "stderr": result.stderr,
            "stdout": result.stdout,
        }))
        sys.exit(1)

    if not os.path.exists(output_path):
        print(json.dumps({"status": "error", "error": "output.html not created"}))
        sys.exit(1)

    # Read and split if needed
    with open(output_path, "r") as f:
        html = f.read()

    html_size = len(html.encode("utf-8"))
    agent_names = {r["agent_name"] for r in clean_rows}

    # Compute summary stats for Claude's confirmation message
    # (so Claude doesn't have to parse the HTML)
    from collections import defaultdict
    agents = defaultdict(lambda: {str(i): 0 for i in range(7)})
    for r in clean_rows:
        agents[r["agent_name"]][r["status_code"]] += r["total_seconds"]

    total_active = sum(
        sum(v for k, v in s.items() if k != "0")
        for s in agents.values()
    )
    total_all = sum(sum(s.values()) for s in agents.values())
    util_pct = round(total_active / total_all * 100, 1) if total_all else 0.0

    # Find top performer and low performers
    ranked = sorted(
        agents.items(),
        key=lambda kv: (
            sum(v for k, v in kv[1].items() if k != "0") /
            max(sum(kv[1].values()), 1) * 100
        ),
        reverse=True,
    )
    top_name = ranked[0][0] if ranked else "N/A"
    top_pct = round(
        sum(v for k, v in ranked[0][1].items() if k != "0") /
        max(sum(ranked[0][1].values()), 1) * 100
    ) if ranked else 0

    low_agents = [
        name for name, s in agents.items()
        if (sum(v for k, v in s.items() if k != "0") / max(sum(s.values()), 1) * 100) < 45
    ]

    # Split HTML if >18KB (conservative threshold to stay within Read tool limits)
    MAX_PART_SIZE = 18000  # bytes
    html_parts = []
    if html_size <= MAX_PART_SIZE:
        html_parts.append(html)
    else:
        # Split at </tr> boundary near midpoint
        mid = len(html) // 2
        try:
            split_point = html.index("</tr>", mid) + len("</tr>")
        except ValueError:
            split_point = mid
        html_parts.append(html[:split_point])
        html_parts.append(html[split_point:])

    output = {
        "status": "ok",
        "step": "render",
        "html_size_bytes": html_size,
        "html_parts_count": len(html_parts),
        "html_parts": html_parts,
        "agent_count": len(agent_names),
        "date_label": date_label,
        "summary": {
            "utilization_pct": util_pct,
            "top_performer": top_name,
            "top_performer_pct": top_pct,
            "low_performers": low_agents,
            "target_pct": 73,
        },
        "email": {
            "subject_prefix": "[TEST] " if args.test_mode else "",
            "subject": f"Agent Status Time Report – {args.company_name} – {date_label}",
        },
    }
    print(json.dumps(output))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Agent Status Report orchestrator — deterministic pipeline for Claude"
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    # --- setup ---
    p_setup = subparsers.add_parser("setup")
    p_setup.add_argument("--company-id", type=int, required=True)
    p_setup.add_argument("--company-name", required=True)
    p_setup.add_argument("--start-date", default=None)
    p_setup.add_argument("--end-date", default=None)
    p_setup.add_argument("--test-mode", action="store_true", default=False)
    p_setup.add_argument("--work-dir", default=None,
                         help="Working directory (default: auto-create temp dir)")

    # --- plan ---
    p_plan = subparsers.add_parser("plan")
    p_plan.add_argument("--company-id", type=int, required=True)
    p_plan.add_argument("--start-date", default=None)
    p_plan.add_argument("--end-date", default=None)
    p_plan.add_argument("--user-ids", required=True,
                        help="JSON array of user_ids from agent-list query")

    # --- render ---
    p_render = subparsers.add_parser("render")
    p_render.add_argument("--company-id", type=int, required=True)
    p_render.add_argument("--company-name", required=True)
    p_render.add_argument("--start-date", default=None)
    p_render.add_argument("--end-date", default=None)
    p_render.add_argument("--test-mode", action="store_true", default=False)
    p_render.add_argument("--work-dir", required=True)
    p_render.add_argument("--rows-json", required=True,
                          help="JSON string of accumulated rows from all Metabase batches")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "plan":
        cmd_plan(args)
    elif args.command == "render":
        cmd_render(args)


if __name__ == "__main__":
    main()
