#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_email_multi.py - Generate a single email-safe HTML report covering MULTIPLE
Aloware accounts, one section per account.

Companion to build_email.py (which renders a single-account report). This script
does not modify or replace build_email.py — other automations depend on the
single-account contract, so it stays untouched. Use this script only when the
caller wants one combined email with N account sections.

Pure Python - zero external dependencies (no matplotlib, no PIL, no pip installs).
Gmail-safe: bgcolor on <td>, no gradients, no rgba(), <p> not <div>, all styles inline.

Input contract (--input path to JSON):
{
  "meta": {
    "skill_name": "agent-status-time-report",
    "date_range": {"start": "2026-08-05", "end": "2026-08-05"},
    "output_format": "email",
    "test_mode": false,
    "generated_at": "..."
  },
  "accounts": [
    {"company_name": "Reach #8 - Advanced Dental Brands", "company_id": 5172, "rows": [...]},
    {"company_name": "Reach #2", "company_id": 2550, "rows": [...]},
    ...
  ]
}

Each row: {"agent_name": "Ana Cruz", "status_code": "1", "total_seconds": 8435}

An account with an empty "rows" list renders as a "No agent activity found" section
instead of crashing - the report is still delivered for accounts that had data.

Usage:
  python build_email_multi.py --input report_data_multi.json --out output.html
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime


STATUS_LABELS = {
    "0": "Offline",
    "1": "Available",
    "2": "Busy",
    "3": "On Break",
    "4": "On Call",
    "5": "Wrap-Up",
    "6": "Ringing",
}
VALID_STATUS_CODES = set(STATUS_LABELS.keys())


def aggregate_rows(rows: list) -> dict:
    agents = defaultdict(lambda: {k: 0 for k in STATUS_LABELS})
    for row in rows:
        name = row.get("agent_name", "Unknown")
        code = str(row.get("status_code", "0"))
        if code not in VALID_STATUS_CODES:
            continue
        secs = int(row.get("total_seconds", 0) or 0)
        agents[name][code] += secs
    return dict(agents)


def fmt_hms(seconds: int) -> str:
    if not seconds:
        return "-"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


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


def compute_kpis(agents: dict) -> dict:
    totals = {code: sum(s.get(code, 0) for s in agents.values()) for code in STATUS_LABELS}
    grand = sum(totals.values())
    pct = lambda v: f"{v/grand*100:.1f}%" if grand else "-"
    return {code: {"time": fmt_hms(totals[code]), "pct": pct(totals[code])} for code in STATUS_LABELS}


def build_exec_summary_html(agents: dict) -> str:
    total_active = sum(sum(v for k, v in s.items() if k != "0") for s in agents.values())
    total_all = sum(sum(s.values()) for s in agents.values())
    util_pct = (total_active / total_all * 100) if total_all else 0.0

    ranked = sorted(
        agents.items(),
        key=lambda kv: (
            sum(v for k, v in kv[1].items() if k != "0") / max(sum(kv[1].values()), 1) * 100,
            sum(v for k, v in kv[1].items() if k != "0"),
        ),
        reverse=True
    )

    def agent_active_pct(s):
        act = sum(v for k, v in s.items() if k != "0")
        tot = max(sum(s.values()), 1)
        return act / tot * 100

    top_name, top_s = ranked[0]
    top_pct = agent_active_pct(top_s)
    top_oncall = top_s.get("4", 0)

    low_agents = [(name, agent_active_pct(s)) for name, s in ranked if agent_active_pct(s) < 45]
    TARGET = 73
    delta = util_pct - TARGET

    oncall_str = f" and {fmt_hms(top_oncall)} on call" if top_oncall else ""
    narrative_parts = [
        f'<strong style="color:#1e2433">Top performer</strong> was ',
        f'<span style="color:#16a34a;font-weight:bold">{top_name}</span> with ',
        f'<span style="color:#16a34a;font-weight:bold">{top_pct:.0f}% active time</span>{oncall_str}. '
    ]

    if low_agents:
        names = [n for n, _ in low_agents]
        if len(names) == 1:
            name_str = names[0]
        elif len(names) == 2:
            name_str = " and ".join(names)
        else:
            name_str = ", ".join(names[:-1]) + ", and " + names[-1]
        narrative_parts.append(
            f'<span style="color:#dc2626;font-weight:bold">{len(low_agents)} agent'
            f'{"s" if len(low_agents)>1 else ""}</span>'
            f' ({name_str}) had '
            f'<span style="color:#dc2626;font-weight:bold">less than 45% active time</span>. '
        )

    if abs(delta) < 1:
        narrative_parts.append(
            f'Team utilization is <strong style="color:#1e2433">{util_pct:.1f}%</strong>,'
            f' right at the {TARGET}% target.'
        )
    elif delta < 0:
        narrative_parts.append(
            f'Team-wide productive time is <strong style="color:#1e2433">{util_pct:.1f}%</strong>'
            f' &#8212; <span style="color:#d97706;font-weight:bold">{abs(delta):.1f} pts below</span>'
            f' the {TARGET}% target.'
        )
    else:
        narrative_parts.append(
            f'Team-wide productive time is <strong style="color:#1e2433">{util_pct:.1f}%</strong>'
            f' &#8212; <span style="color:#16a34a;font-weight:bold">{delta:.1f} pts above</span>'
            f' the {TARGET}% target.'
        )

    narrative_html = "".join(narrative_parts)
    util_color = "#16a34a" if util_pct >= TARGET else "#d97706"

    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:16px">'
        f'<tr>'
        f'<td bgcolor="#f1f5f9" style="padding:20px 24px;vertical-align:top;border:1px solid #e2e8f0">'
        f'<p style="margin:0 0 6px 0;font-size:10px;font-weight:bold;letter-spacing:1px;'
        f'text-transform:uppercase;color:#475569;font-family:Arial,sans-serif">SUMMARY</p>'
        f'<p style="margin:0;font-size:14px;line-height:1.7;color:#1e293b;font-family:Arial,sans-serif">'
        f'{narrative_html}</p>'
        f'</td>'
        f'<td bgcolor="#f1f5f9" width="150" style="padding:20px 24px;text-align:center;'
        f'vertical-align:middle;border:1px solid #e2e8f0;border-left:none">'
        f'<p style="margin:0;font-size:44px;font-weight:bold;line-height:1;color:{util_color};'
        f'font-family:Arial,sans-serif">{util_pct:.1f}<span style="font-size:20px">%</span></p>'
        f'<p style="margin:4px 0 0 0;font-size:10px;color:#475569;text-transform:uppercase;'
        f'letter-spacing:1px;font-family:Arial,sans-serif">Team Utilization</p>'
        f'</td>'
        f'</tr></table>'
    )


def _account_header(company: str, company_id, agent_count=None) -> str:
    suffix = f" &middot; {agent_count} agents" if agent_count is not None else ""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px">'
        f'<tr><td bgcolor="#eef2ff" style="padding:14px 24px;border:1px solid #c7d2fe">'
        f'<p style="margin:0;font-size:16px;font-weight:bold;color:#1e2433;font-family:Arial,sans-serif">{company} '
        f'<span style="font-size:12px;color:#6b7280;font-weight:normal">(ID {company_id}){suffix}</span></p>'
        f'</td></tr></table>'
    )


def build_account_section(agents: dict, company: str, company_id, date_label: str) -> str:
    """Render one account's section: header, exec summary, KPI cards, breakdown table.
    Renders a graceful placeholder when the account has no agent data."""
    if not agents:
        return (
            _account_header(company, company_id)
            + '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:32px">'
              '<tr><td bgcolor="#ffffff" style="padding:16px 24px;border:1px solid #e2e8f0">'
              f'<p style="margin:0;font-size:13px;color:#6b7280;font-family:Arial,sans-serif">'
              f'No agent activity found for {date_label}.</p>'
              '</td></tr></table>'
        )

    kpis = compute_kpis(agents)
    sorted_agents = sorted(
        agents.items(),
        key=lambda kv: kv[1].get("4", 0) + kv[1].get("1", 0),
        reverse=True,
    )

    kpi_configs = [
        ("1", "Available", "#22c55e"),
        ("4", "On Call", "#3b82f6"),
        ("5", "Wrap-Up", "#a855f7"),
        ("2", "Busy", "#f97316"),
        ("3", "On Break", "#eab308"),
        ("0", "Offline", "#94a3b8"),
    ]

    kpi_cells = ""
    for i, (code, label, color) in enumerate(kpi_configs):
        right_pad = "4px" if i < len(kpi_configs) - 1 else "0"
        kpi_cells += (
            f'<td style="padding:0 {right_pad} 0 0;vertical-align:top">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td bgcolor="#ffffff" style="padding:14px 16px;border-top:3px solid {color};'
            f'border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0">'
            f'<p style="margin:0 0 4px 0;font-size:10px;color:#6b7280;text-transform:uppercase;'
            f'letter-spacing:.5px;font-family:Arial,sans-serif">{label}</p>'
            f'<p style="margin:0;font-size:20px;font-weight:bold;color:#1e2433;font-family:Arial,sans-serif">'
            f'{kpis[code]["time"]}</p>'
            f'<p style="margin:2px 0 0 0;font-size:11px;color:#6b7280;font-family:Arial,sans-serif">'
            f'{kpis[code]["pct"]} of total</p>'
            f'</td></tr></table></td>'
        )

    table_rows = ""
    for i, (agent_name, s) in enumerate(sorted_agents):
        active = sum(v for k, v in s.items() if k != "0")
        total = active + s.get("0", 0)
        pct_val = f"{active/total*100:.1f}%" if total else "0.0%"
        pct_w = f"{active/total*100:.0f}%" if total else "0%"

        def cell(code, _s=s):
            val = _s.get(code, 0)
            return fmt_hms(val) if val else '<span class="nd">&#8212;</span>'

        row_cls = "ro" if i % 2 == 0 else "ra"
        table_rows += (
            f'<tr class="{row_cls}">'
            f'<td class="an">{agent_name}</td>'
            f'<td class="ac"><table cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td class="pb"><div class="bar" style="width:{pct_w}"></div></td>'
            f'<td class="pv" data-metric="active">{pct_val}</td>'
            f'</tr></table></td>'
            f'<td class="s1">{cell("1")}</td>'
            f'<td class="s4">{cell("4")}</td>'
            f'<td class="s5">{cell("5")}</td>'
            f'<td class="s2">{cell("2")}</td>'
            f'<td class="s3">{cell("3")}</td>'
            f'<td class="s6">{cell("6")}</td>'
            f'<td class="s0">{cell("0")}</td>'
            f'</tr>'
        )

    agent_count = len(agents)
    exec_summary_html = build_exec_summary_html(agents)

    return (
        _account_header(company, company_id, agent_count)
        + exec_summary_html
        + '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:16px"><tr>'
        + kpi_cells + '</tr></table>'
        + '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:32px">'
        + '<tr><td bgcolor="#ffffff" style="padding:20px 24px;border:1px solid #e2e8f0">'
        + f'<p style="margin:0 0 14px 0;font-size:14px;font-weight:bold;color:#1e2433;font-family:Arial,sans-serif">Agent Status Breakdown - {date_label}</p>'
        + '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size:13px;border-collapse:collapse">'
        + '<thead><tr style="border-bottom:2px solid #e5e7eb">'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;font-weight:600;font-family:Arial,sans-serif">Agent</th>'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;font-weight:600;font-family:Arial,sans-serif">Active %</th>'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#22c55e;text-transform:uppercase;letter-spacing:.5px;font-weight:600;font-family:Arial,sans-serif">Available</th>'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#3b82f6;text-transform:uppercase;letter-spacing:.5px;font-weight:600;font-family:Arial,sans-serif">On Call</th>'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#a855f7;text-transform:uppercase;letter-spacing:.5px;font-weight:600;font-family:Arial,sans-serif">Wrap-Up</th>'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#f97316;text-transform:uppercase;letter-spacing:.5px;font-weight:600;font-family:Arial,sans-serif">Busy</th>'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#eab308;text-transform:uppercase;letter-spacing:.5px;font-weight:600;font-family:Arial,sans-serif">On Break</th>'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#06b6d4;text-transform:uppercase;letter-spacing:.5px;font-weight:600;font-family:Arial,sans-serif">Ringing</th>'
        + '<th style="text-align:left;padding:9px 12px;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;font-weight:600;font-family:Arial,sans-serif">Offline</th>'
        + '</tr></thead>'
        + f'<tbody>{table_rows}</tbody>'
        + '</table>'
        + '</td></tr></table>'
    )


def build_multi_email_html(accounts: list, date_label: str) -> str:
    """accounts: list of {"company_name", "company_id", "agents"} (agents may be {})"""
    n = len(accounts)
    sections = "".join(
        build_account_section(a["agents"], a["company_name"], a["company_id"], date_label)
        for a in accounts
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Agent Status Time Report - {date_label}</title>
<style>
.ro{{background:#fff}}.ra{{background:#fafafa}}
.an{{padding:9px 12px;font-weight:600;color:#1e2433;white-space:nowrap;border-bottom:1px solid #f3f4f6}}
.ac{{padding:9px 12px;border-bottom:1px solid #f3f4f6}}
.pb{{width:60px;background:#f1f5f9;border-radius:4px;overflow:hidden;vertical-align:middle}}
.bar{{background:#2c5dbd;height:8px;border-radius:4px}}
.pv{{padding-left:6px;font-size:12px;font-weight:600;color:#1e2433;white-space:nowrap}}
.s1{{padding:9px 12px;color:#22c55e;font-weight:500;border-bottom:1px solid #f3f4f6}}
.s4{{padding:9px 12px;color:#3b82f6;font-weight:500;border-bottom:1px solid #f3f4f6}}
.s5{{padding:9px 12px;color:#a855f7;font-weight:500;border-bottom:1px solid #f3f4f6}}
.s2{{padding:9px 12px;color:#f97316;font-weight:500;border-bottom:1px solid #f3f4f6}}
.s3{{padding:9px 12px;color:#eab308;font-weight:500;border-bottom:1px solid #f3f4f6}}
.s6{{padding:9px 12px;color:#06b6d4;font-weight:500;border-bottom:1px solid #f3f4f6}}
.s0{{padding:9px 12px;color:#94a3b8;font-weight:500;border-bottom:1px solid #f3f4f6}}
.nd{{color:#d1d5db}}
</style>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,sans-serif;color:#1e2433">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="padding:16px"><tr><td>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:16px">
  <tr><td bgcolor="#1e2433" style="padding:20px 28px">
    <p style="margin:0;font-size:20px;font-weight:bold;color:#ffffff;font-family:Arial,sans-serif">Agent Status Time Report</p>
    <p style="margin:4px 0 0 0;font-size:13px;color:#94a3b8;font-family:Arial,sans-serif">{date_label} &nbsp;&bull;&nbsp; {n} accounts</p>
  </td></tr></table>

  {sections}
  <p style="text-align:center;font-size:12px;color:#6b7280;font-family:Arial,sans-serif">
    {date_label} &nbsp;&middot;&nbsp; Source: Aloware agent_audits
  </p>

</td></tr></table>
</body></html>
"""


def main():
    parser = argparse.ArgumentParser(description="Build a combined multi-account Agent Status Report email")
    parser.add_argument("--input", required=True, help="Path to multi-account JSON contract")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.input) as f:
        contract = json.load(f)

    meta = contract.get("meta", {})
    dr = meta.get("date_range", {})
    start_date = dr.get("start", "")
    end_date = dr.get("end", start_date)
    date_label = format_date_label(start_date, end_date)

    accounts_in = contract.get("accounts", [])
    if not accounts_in:
        print("No accounts provided in contract - aborting.", file=sys.stderr)
        sys.exit(1)

    accounts = []
    for a in accounts_in:
        agents = aggregate_rows(a.get("rows", []))
        accounts.append({
            "company_name": a.get("company_name", "Unknown Company"),
            "company_id": a.get("company_id", 0),
            "agents": agents,
        })
        print(f"  {a.get('company_name')}: {len(agents)} agents" if agents else f"  {a.get('company_name')}: no activity")

    print(f"Rendering combined report for {len(accounts)} accounts...")
    html = build_multi_email_html(accounts, date_label)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Email HTML written to: {args.out} ({len(html):,} chars)")


if __name__ == "__main__":
    main()
