#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
query_report.py - Agent Status Time Report: SQL generator + data contract writer.

This script owns the SQL, batching logic, and data contract format.
Claude never writes or interprets SQL — it just executes what this script produces.

TWO MODES:

  Mode A — generate-sql (step 1 of 2):
    Accepts a list of user_ids (JSON array) and prints the batch SQL queries
    that Claude must execute verbatim against Metabase (database_id=2).

    python query_report.py generate-sql \\
        --company-id 6870 \\
        --start-date 2026-04-13 \\
        --end-date   2026-04-13 \\
        --user-ids   '[101,102,103,...]'

    Output: JSON array of SQL strings, one per batch of 60 agents.

  Mode B — build-contract (step 2 of 2):
    Accepts accumulated query results (list of row dicts) and writes the
    data contract JSON consumed by build_email.py.

    python query_report.py build-contract \\
        --company-id   6870 \\
        --company-name "Olala Homes" \\
        --start-date   2026-04-13 \\
        --end-date     2026-04-13 \\
        --rows-json    /tmp/rows.json \\
        --out          /tmp/report_data.json \\
        [--test-mode]

  ALSO INCLUDED:
    The agent-list SQL is printed by: generate-sql --agent-list-only
    This lets Claude run Step 1 (get user_ids) without any SQL in the skill.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta


BATCH_SIZE = 60
DATABASE_ID = 2  # Aloware production DB in Metabase


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def resolve_dates(start_arg, end_arg):
    """Resolve date shortcut strings to (start_date, end_date) YYYY-MM-DD."""
    from datetime import date
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


def end_date_exclusive(end_date: str) -> str:
    """Return the day after end_date as YYYY-MM-DD."""
    d = datetime.strptime(end_date, "%Y-%m-%d")
    return (d + timedelta(days=1)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# SQL builders (canonical — single source of truth)
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
    batch_ids = ", ".join(str(uid) for uid in user_ids)
    return f"""WITH transitions AS (
  SELECT
    aa.user_id,
    (u.first_name || ' ' || u.last_name) AS agent_name,
    aa."to"                               AS status_code,
    aa.created_at                         AS started_at,
    LEAD(aa.created_at) OVER (
      PARTITION BY aa.user_id
      ORDER BY aa.created_at
    )                                     AS next_at
  FROM aloware.agent_audits aa
  JOIN aloware.users u ON u.id = aa.user_id
  WHERE aa.company_id = {company_id}
    AND aa.user_id    IN ({batch_ids})
    AND aa.property   = 'agent_status'
    AND aa.created_at >= '{start_date} 00:00:00'
    AND aa.created_at <  '{end_excl} 00:00:00'
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
      ELSE '{end_excl} 00:00:00'
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
ORDER BY agent_name, status_code"""


# ---------------------------------------------------------------------------
# Mode A: generate-sql
# ---------------------------------------------------------------------------

def cmd_generate_sql(args):
    start_date, end_date = resolve_dates(args.start_date, args.end_date)
    end_excl = end_date_exclusive(end_date)

    # Always print the agent-list SQL first as a separate key
    agent_sql = agent_list_sql(args.company_id, start_date, end_excl)

    if args.agent_list_only:
        print(json.dumps({
            "mode": "agent_list",
            "database_id": DATABASE_ID,
            "row_limit": 500,
            "sql": agent_sql,
            "start_date": start_date,
            "end_date": end_date,
            "end_date_exclusive": end_excl,
        }, indent=2))
        return

    if not args.user_ids:
        print("ERROR: --user-ids required (unless --agent-list-only)", file=sys.stderr)
        sys.exit(1)

    try:
        user_ids = json.loads(args.user_ids)
    except json.JSONDecodeError:
        print("ERROR: --user-ids must be a valid JSON array, e.g. '[101,102,103]'", file=sys.stderr)
        sys.exit(1)

    if not user_ids:
        print("ERROR: --user-ids array is empty", file=sys.stderr)
        sys.exit(1)

    batches = [user_ids[i:i + BATCH_SIZE] for i in range(0, len(user_ids), BATCH_SIZE)]
    batch_queries = []
    for idx, batch in enumerate(batches, 1):
        sql = status_batch_sql(args.company_id, batch, start_date, end_excl)
        batch_queries.append({
            "batch": idx,
            "total_batches": len(batches),
            "agent_count": len(batch),
            "database_id": DATABASE_ID,
            "row_limit": 500,
            "sql": sql,
        })

    output = {
        "mode": "status_batches",
        "company_id": args.company_id,
        "start_date": start_date,
        "end_date": end_date,
        "end_date_exclusive": end_excl,
        "total_agents": len(user_ids),
        "total_batches": len(batches),
        "queries": batch_queries,
    }
    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Mode B: build-contract
# ---------------------------------------------------------------------------

def cmd_build_contract(args):
    start_date, end_date = resolve_dates(args.start_date, args.end_date)

    # Load rows from file
    try:
        with open(args.rows_json) as f:
            rows = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: rows file not found: {args.rows_json}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in rows file: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(rows, list):
        print("ERROR: rows file must contain a JSON array", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("ERROR: rows array is empty — no data to render", file=sys.stderr)
        sys.exit(1)

    # Validate row structure
    required_keys = {"agent_name", "status_code", "total_seconds"}
    sample = rows[0]
    missing = required_keys - set(sample.keys())
    if missing:
        print(f"ERROR: rows missing required keys: {missing}", file=sys.stderr)
        print(f"  Got keys: {set(sample.keys())}", file=sys.stderr)
        sys.exit(1)

    # Normalise: ensure total_seconds is int, status_code is string
    clean_rows = []
    for r in rows:
        try:
            clean_rows.append({
                "agent_name":    str(r["agent_name"]),
                "status_code":   str(r["status_code"]),
                "total_seconds": int(r["total_seconds"] or 0),
            })
        except (KeyError, TypeError, ValueError) as e:
            print(f"WARNING: skipping malformed row {r}: {e}", file=sys.stderr)
            continue

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

    with open(args.out, "w") as f:
        json.dump(contract, f)

    agent_names = {r["agent_name"] for r in clean_rows}
    print(f"Data contract written to: {args.out}")
    print(f"  {len(clean_rows)} rows, {len(agent_names)} agents, test_mode={args.test_mode}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Agent Status Report: SQL generator and data contract builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    # --- generate-sql ---
    p_gen = subparsers.add_parser(
        "generate-sql",
        help="Print batch SQL queries for Claude to execute via Metabase MCP",
    )
    p_gen.add_argument("--company-id",      type=int, required=True)
    p_gen.add_argument("--start-date",      default=None)
    p_gen.add_argument("--end-date",        default=None)
    p_gen.add_argument("--user-ids",        default=None,
                       help="JSON array of user_ids from the agent-list query")
    p_gen.add_argument("--agent-list-only", action="store_true",
                       help="Only print the agent-list SQL (Step 1)")

    # --- build-contract ---
    p_build = subparsers.add_parser(
        "build-contract",
        help="Write data contract JSON from accumulated Metabase rows",
    )
    p_build.add_argument("--company-id",   type=int, required=True)
    p_build.add_argument("--company-name",           required=True)
    p_build.add_argument("--start-date",             default=None)
    p_build.add_argument("--end-date",               default=None)
    p_build.add_argument("--rows-json",              required=True,
                         help="Path to JSON file containing accumulated rows from all batches")
    p_build.add_argument("--out",                    required=True,
                         help="Output path for report_data.json")
    p_build.add_argument("--test-mode",   action="store_true", default=False)

    args = parser.parse_args()

    if args.command == "generate-sql":
        cmd_generate_sql(args)
    elif args.command == "build-contract":
        cmd_build_contract(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
