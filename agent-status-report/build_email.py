#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_email.py - Generate a fully static, email-safe HTML report.

Pure Python — zero external dependencies (no matplotlib, no PIL, no pip installs).
Produces self-contained inline-CSS HTML that renders identically in Gmail, Outlook,
and Apple Mail. No images, no JavaScript, no <style> blocks.

Usage:
  python build_email.py --input report_data.json --out output.html
  python build_email.py --rows '[...]' --company "Acme" --start-date 2026-04-13 --out output.html
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
STATUS_COLORS = {
    "0": "#94a3b8",
    "1": "#22c55e",
    "2": "#f97316",
    "3": "#eab308",
    "4": "#3b82f6",
    "5": "#a855f7",
    "6": "#06b6d4",
}
CHART_ORDER = ["1", "4", "5", "2", "3", "6", "0"]

VALID_STATUS_CODES = set(STATUS_LABELS.keys())


def aggregate_rows(rows: list) -> dict:
    """Aggregate raw query rows into {agent_name: {status_code: total_seconds}}.

    Filters out any non-numeric status codes (e.g. legacy "offline" string values)
    to avoid inflating or misattributing time. Only codes 0-6 are valid.
    """
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
    total_active = sum(
        sum(v for k, v in s.items() if k != "0")
        for s in agents.values()
    )
    total_all = sum(sum(s.values()) for s in agents.values())
    util_pct = (total_active / total_all * 100) if total_all else 0.0

    ranked = sorted(
        agents.items(),
        key=lambda kv: (
            sum(v for k, v in kv[1].items() if k != "0") /
            max(sum(kv[1].values()), 1) * 100,
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
        f'<strong>Top performer</strong> was ',
        f'<span style="color:#4ade80;font-weight:700">{top_name}</span> with ',
        f'<span style="color:#4ade80;font-weight:700">{top_pct:.0f}% active time</span>{oncall_str}. '
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
            f'<span style="color:#f87171;font-weight:700">{len(low_agents)} agent'
            f'{"s" if len(low_agents)>1 else ""}</span>'
            f' - {name_str} - had '
            f'<span style="color:#f87171;font-weight:700">less than 45% active time</span>. '
        )

    if abs(delta) < 1:
        narrative_parts.append(
            f'Team utilization is <strong style="color:#fff">{util_pct:.1f}%</strong>,'
            f' right at the {TARGET}% target.'
        )
    elif delta < 0:
        narrative_parts.append(
            f'Team-wide productive time is <strong style="color:#fff">{util_pct:.1f}%</strong>'
            f' - <span style="color:#fbff24;font-weight:700">{abs(delta):.1f} points below</span>'
            f' the {TARGET}% target.'
        )
    else:
        narrative_parts.append(
            f'Team-wide productive time is <strong style="color:#fff">{util_pct:.1f}%</strong>'
            f' - <span style="color:#4ade80;font-weight:700">{delta:.1f} points above</span>'
            f' the {TARGET}% target.'
        )

    narrative_html = "".join(narrative_parts)
    score_bar_width = f"{min(util_pct, 100):.1f}%"

    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:linear-gradient(135deg,#1a2744 0%,#2c3e6b 100%);border-radius:10px;margin-bottom:16px">'
        f'<tr>'
        f'<td style="padding:24px 28px;vertical-align:middle">'
        f'<div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;'
        f'color:rgba(255,255,255,0.45);margin-bottom:10px">Today\'s Summary</div>'
        f'<div style="font-size:14px;line-height:1.65;color:rgba(255,255,255,0.88)">{narrative_html}</div>'
        f'</td>'
        f'<td style="padding:24px 28px;text-align:center;vertical-align:middle;white-space:nowrap;border-left:1px solid rgba(255,255,255,0.1)">'
        f'<div style="font-size:52px;font-weight:900;line-height:1;color:#fff;letter-spacing:-1px;">'
        f'{util_pct:.1f}<span style="font-size:26px;font-weight:600;color:rgba(255,255,255,0.6)">%</span></div>'
        f'<div style="font-size:10px;color:rgba(255,255,255,0.45);text-transform:uppercase;letter-spacing:1px;margin-top:4px;">'
        f'Team Utilization</div>'
        f'<table cellpadding="0" cellspacing="0" border="0" style="margin:8px auto 0;width:110px">'
        f'<tr><td style="background:rgba(255,255,255,0.15);border-radius:3px;height:6px;overflow:hidden">'
        f'<div style="background:linear-gradient(90deg,#4ade80,#22c55e);height:6px;width:{score_bar_width};border-radius:3px"></div>'
        f'</td></tr></table>'
        f'</td>'
        f'</tr></table>'
    )


def build_email_html(agents, company, date_label, company_id):
    """Build the full email HTML. No images — pure table-based layout."""
    kpis = compute_kpis(agents)

    sorted_agents = sorted(
        agents.items(),
        key=lambda kv: kv[1].get("4", 0) + kv[1].get("1", 0),
        reverse=True,
    )

    kpi_configs = [
        ("1", "Available",  "#22c55e"),
        ("4", "On Call",    "#3b82f6"),
        ("5", "Wrap-Up",    "#a855f7"),
        ("2", "Busy",       "#f97316"),
        ("3", "On Break",   "#eab308"),
        ("0", "Offline",    "#94a3b8"),
    ]
    kpi_cells = ""
    for code, label, color in kpi_configs:
        kpi_cells += (
            f'<td style="padding:0 6px 0 0;vertical-align:top">'
            f'<div style="background:#fff;border-radius:8px;padding:14px 16px;border-top:3px solid {color};min-width:100px">'
            f'<div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:#1e2433">{kpis[code]["time"]}</div>'
            f'<div style="font-size:11px;color:#6b7280;margin-top:2px">{kpis[code]["pct"]} of total</div>'
            f'</div></td>'
        )

    table_rows = ""
    for i, (agent_name, s) in enumerate(sorted_agents):
        active = sum(v for k, v in s.items() if k != "0")
        total = active + s.get("0", 0)
        pct_val = f"{active/total*100:.1f}%" if total else "0.0%"
        pct_w = f"{active/total*100:.0f}%" if total else "0%"

        def cell(code, _s=s):
            val = _s.get(code, 0)
            return fmt_hms(val) if val else '<span style="color:#d1d5db">&#8212;</span>'

        row_bg = "#fff" if i % 2 == 0 else "#fafafa"
        table_rows += (
            f'<tr style="background:{row_bg}">'
            f'<td style="padding:9px 12px;font-weight:600;color:#1e2433;white-space:nowrap;border-bottom:1px solid #f3f4f6">{agent_name}</td>'
            f'<td style="padding:9px 12px;border-bottom:1px solid #f3f4f6">'
            f'<table cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="width:60px;background:#f1f5f9;border-radius:4px;overflow:hidden;vertical-align:middle">'
            f'<div style="background:#2c5dbd;height:8px;width:{pct_w};border-radius:4px"></div></td>'
            f'<td style="padding-left:6px;font-size:12px;font-weight:600;color:#1e2433;white-space:nowrap">{pct_val}</td>'
            f'</tr></table></td>'
            f'<td style="padding:9px 12px;color:#22c55e;font-weight:500;border-bottom:1px solid #f3f4f6">{cell("1")}</td>'
            f'<td style="padding:9px 12px;color:#3b82f6;font-weight:500;border-bottom:1px solid #f3f4f6">{cell("4")}</td>'
            f'<td style="padding:9px 12px;color:#a855f7;font-weight:500;border-bottom:1px solid #f3f4f6">{cell("5")}</td>'
            f'<td style="padding:9px 12px;color:#f97316;font-weight:500;border-bottom:1px solid #f3f4f6">{cell("2")}</td>'
            f'<td style="padding:9px 12px;color:#eab308;font-weight:500;border-bottom:1px solid #f3f4f6">{cell("3")}</td>'
            f'<td style="padding:9px 12px;color:#06b6d4;font-weight:500;border-bottom:1px solid #f3f4f6">{cell("6")}</td>'
            f'<td style="padding:9px 12px;color:#94a3b8;font-weight:500;border-bottom:1px solid #f3f4f6">{cell("0")}</td>'
            f'</tr>'
        )

    agent_count = len(agents)
    exec_summary_html = build_exec_summary_html(agents)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Agent Status Time Report - {company}</title></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1e2433">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f0f2f5;padding:16px"><tr><td>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#1a2744;border-radius:10px;margin-bottom:16px">
  <tr><td style="padding:20px 28px">
    <div style="font-size:20px;font-weight:700;color:#ffffff">Agent Status Time Report</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.65);margin-top:3px">{company} &nbsp;&middot;&nbsp; {date_label} &nbsp;&middot;&nbsp; {agent_count} agents</div>
  </td></tr></table>

  {exec_summary_html}
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:16px">
  <tr>{kpi_cells}</tr></table>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:10px;margin-bottom:16px">
  <tr><td style="padding:20px 24px">
    <div style="font-size:14px;font-weight:600;margin-bottom:14px;color:#1e2433">Agent Status Breakdown - {date_label}</div>
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size:13px;border-collapse:collapse">
      <thead><tr style="border-bottom:2px solid #e5e7eb">
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;font-weight:600">Agent</th>
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;font-weight:600">Active %</th>
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#22c55e;text-transform:uppercase;letter-spacing:.5px;font-weight:600">Available</th>
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#3b82f6;text-transform:uppercase;letter-spacing:.5px;font-weight:600">On Call</th>
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#a855f7;text-transform:uppercase;letter-spacing:.5px;font-weight:600">Wrap-Up</th>
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#f97316;text-transform:uppercase;letter-spacing:.5px;font-weight:600">Busy</th>
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#eab308;text-transform:uppercase;letter-spacing:.5px;font-weight:600">On Break</th>
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#06b6d4;text-transform:uppercase;letter-spacing:.5px;font-weight:600">Ringing</th>
        <th style="text-align:left;padding:9px 12px;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;font-weight:600">Offline</th>
      </tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </td></tr></table>

  <div style="text-align:center;font-size:12px;color:#6b7280;padding:8px 0">
    {date_label} &nbsp;&middot;&nbsp; {company} (ID {company_id}) &nbsp;&middot;&nbsp; Source: Aloware agent_audits
  </div>

</td></tr></table>
</body></html>
"""


def main():
    parser = argparse.ArgumentParser(description="Build email-safe Agent Status Report HTML")
    parser.add_argument("--input",      default=None)
    parser.add_argument("--rows",       default=None)
    parser.add_argument("--company",    default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date",   default=None)
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--out",        required=True)
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            contract = json.load(f)
        meta       = contract.get("meta", {})
        rows       = contract.get("rows", [])
        company    = meta.get("company_name", "Unknown Company")
        company_id = meta.get("company_id", 0)
        dr         = meta.get("date_range", {})
        start_date = dr.get("start", "")
        end_date   = dr.get("end", start_date)
    else:
        if not args.rows or not args.company or not args.start_date:
            print("ERROR: must provide --input or (--rows + --company + --start-date)", file=sys.stderr)
            sys.exit(1)
        rows       = json.loads(args.rows)
        company    = args.company
        company_id = args.company_id
        start_date = args.start_date
        end_date   = args.end_date or args.start_date

    date_label = format_date_label(start_date, end_date)
    agents     = aggregate_rows(rows)

    if not agents:
        print("No agent data found - aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"Rendering report for {len(agents)} agents...")

    html = build_email_html(agents, company, date_label, company_id)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Email HTML written to: {args.out} ({len(html):,} chars)")


if __name__ == "__main__":
    main()
