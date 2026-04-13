#!/usr/bin/env python3
"""
build_email.py — Generate a fully static, email-safe HTML report with embedded chart images.

Email clients strip <script> tags, so this script pre-renders charts server-side
using matplotlib and embeds them as base64 JPEGs. The result is a single HTML string
safe to paste directly into gmail_create_draft as the body.

Optimized for small output size (~25-30 KB) so the full HTML reliably passes through
LLM context windows and MCP tool calls without truncation.

Usage:
  python build_email.py \
    --rows    '[{"agent_name":"Ana Cruz","status_code":"1","total_seconds":8435}, ...]' \
    --company "Debt Freedom USA" \
    --start-date 2026-04-06 \
    --end-date   2026-04-06 \
    --company-id 6364 \
    --out /tmp/agent-status-email.html

Output: A standalone HTML file. Paste its entire contents as the email body.
"""

import argparse
import base64
import io
import json
import sys
from collections import defaultdict
from datetime import datetime


# ── Status metadata ────────────────────────────────────────────────────────────
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
CHART_ORDER = ["1", "4", "5", "2", "3", "6", "0"]  # display order


# ── Data helpers ───────────────────────────────────────────────────────────────
def aggregate_rows(rows: list) -> dict:
    """Return {agent_name: {status_code: total_seconds}} summed across all rows."""
    agents = defaultdict(lambda: {k: 0 for k in STATUS_LABELS})
    for row in rows:
        name = row.get("agent_name", "Unknown")
        code = str(row.get("status_code", "0"))
        secs = int(row.get("total_seconds", 0) or 0)
        agents[name][code] += secs
    return dict(agents)


def fmt_hms(seconds: int) -> str:
    if not seconds:
        return "\u2014"
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
            return f"{start.strftime('%B %-d, %Y')} \u2013 {end.strftime('%B %-d, %Y')}"
        if start.month != end.month:
            return f"{start.strftime('%B %-d')} \u2013 {end.strftime('%B %-d, %Y')}"
        return f"{start.strftime('%B %-d')}\u2013{end.strftime('%-d, %Y')}"
    except Exception:
        return end_str or start_str


# ── Chart generation (optimized for small file size) ──────────────────────────
def to_base64_jpeg(fig, quality: int = 30, dpi: int = 48) -> str:
    """Render a matplotlib figure to a base64-encoded JPEG string.

    Tuned for email: low DPI + aggressive JPEG compression keeps each chart
    under ~8 KB of base64 while remaining perfectly readable at email width.
    """
    from PIL import Image
    buf_png = io.BytesIO()
    fig.savefig(buf_png, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf_png.seek(0)
    img = Image.open(buf_png).convert("RGB")
    buf_jpg = io.BytesIO()
    img.save(buf_jpg, format="JPEG", quality=quality, optimize=True)
    buf_jpg.seek(0)
    return base64.b64encode(buf_jpg.read()).decode("utf-8")


def make_stacked_bar(agents: dict) -> str:
    """Horizontal stacked bar chart: time per status per agent, sorted by On Call + Available."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    sorted_agents = sorted(
        agents.items(),
        key=lambda kv: kv[1].get("4", 0) + kv[1].get("1", 0)
    )
    agent_names = [a for a, _ in sorted_agents]
    n = len(agent_names)

    fig_height = max(3, n * 0.5 + 1.5)
    fig, ax = plt.subplots(figsize=(8, fig_height), facecolor="#f8f9fa")
    ax.set_facecolor("#ffffff")

    lefts = [0.0] * n
    for code in CHART_ORDER:
        vals = [s.get(code, 0) / 3600 for _, s in sorted_agents]
        ax.barh(agent_names, vals, left=lefts,
                color=STATUS_COLORS[code],
                label=STATUS_LABELS[code],
                height=0.65)
        lefts = [l + v for l, v in zip(lefts, vals)]

    ax.set_xlabel("Hours", fontsize=9, color="#6b7280")
    ax.set_title("Time in Each Status per Agent \u2014 sorted by On Call + Available",
                 fontsize=10, color="#1e2433", pad=8, loc="left")
    ax.tick_params(axis="y", labelsize=8, colors="#1e2433")
    ax.tick_params(axis="x", labelsize=7, colors="#6b7280")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", color="#f0f0f0", linewidth=0.8)
    ax.set_axisbelow(True)

    handles = [
        mpatches.Patch(color=STATUS_COLORS[c], label=STATUS_LABELS[c])
        for c in CHART_ORDER
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=7, framealpha=0.9, ncol=4)

    fig.tight_layout()
    b64 = to_base64_jpeg(fig)
    plt.close(fig)
    return b64


def make_donut(agents: dict) -> str:
    """Donut chart: team-wide time distribution across statuses."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    totals = {code: sum(s.get(code, 0) for s in agents.values()) for code in CHART_ORDER}
    labels = [STATUS_LABELS[c] for c in CHART_ORDER if totals[c] > 0]
    sizes  = [totals[c] for c in CHART_ORDER if totals[c] > 0]
    colors = [STATUS_COLORS[c] for c in CHART_ORDER if totals[c] > 0]

    fig, ax = plt.subplots(figsize=(4, 3.5), facecolor="#f8f9fa")
    ax.set_facecolor("#f8f9fa")

    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, colors=colors,
        autopct=lambda p: f"{p:.0f}%" if p > 4 else "",
        pctdistance=0.78,
        wedgeprops={"width": 0.5, "edgecolor": "white", "linewidth": 2},
        startangle=90,
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color("white")
        at.set_fontweight("bold")

    ax.set_title("Team-Wide Status Distribution", fontsize=10, color="#1e2433", pad=6)
    ax.legend(wedges, labels, loc="lower center", fontsize=7,
              bbox_to_anchor=(0.5, -0.08), ncol=2, framealpha=0.9)

    fig.tight_layout()
    b64 = to_base64_jpeg(fig)
    plt.close(fig)
    return b64


# ── KPI computation ────────────────────────────────────────────────────────────
def compute_kpis(agents: dict) -> dict:
    totals = {code: sum(s.get(code, 0) for s in agents.values()) for code in STATUS_LABELS}
    grand = sum(totals.values())
    pct = lambda v: f"{v/grand*100:.1f}%" if grand else "\u2014"
    return {code: {"time": fmt_hms(totals[code]), "pct": pct(totals[code])} for code in STATUS_LABELS}


# ── Email HTML builder ─────────────────────────────────────────────────────────
def build_email_html(agents, company, date_label, company_id, bar_b64, donut_b64):
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
        total  = active + s.get("0", 0)
        pct_val = f"{active/total*100:.1f}%" if total else "0.0%"
        pct_w   = f"{active/total*100:.0f}%" if total else "0%"

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

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Agent Status Time Report &#8211; {company}</title></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1e2433">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f0f2f5;padding:16px"><tr><td>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#1a2744;border-radius:10px;margin-bottom:16px">
  <tr><td style="padding:20px 28px">
    <div style="font-size:20px;font-weight:700;color:#ffffff">Agent Status Time Report</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.65);margin-top:3px">{company} &nbsp;&middot;&nbsp; {date_label} &nbsp;&middot;&nbsp; {agent_count} agents</div>
  </td></tr></table>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:16px">
  <tr>{kpi_cells}</tr></table>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:16px"><tr>
    <td width="68%" style="padding-right:8px;vertical-align:top">
      <div style="background:#fff;border-radius:10px;padding:16px 20px">
        <img src="data:image/jpeg;base64,{bar_b64}" alt="Status per agent" width="100%" style="display:block;max-width:100%">
      </div>
    </td>
    <td width="32%" style="vertical-align:top">
      <div style="background:#fff;border-radius:10px;padding:16px 20px">
        <img src="data:image/jpeg;base64,{donut_b64}" alt="Status distribution" width="100%" style="display:block;max-width:100%">
      </div>
    </td>
  </tr></table>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:10px;margin-bottom:16px">
  <tr><td style="padding:20px 24px">
    <div style="font-size:14px;font-weight:600;margin-bottom:14px;color:#1e2433">Agent Status Breakdown &mdash; {date_label}</div>
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
</body></html>"""


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Build email-safe Agent Status Report HTML")
    parser.add_argument("--rows",       required=True)
    parser.add_argument("--company",    required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date",   default=None)
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--out",        required=True)
    args = parser.parse_args()

    rows = json.loads(args.rows)
    end  = args.end_date or args.start_date
    date_label = format_date_label(args.start_date, end)
    agents = aggregate_rows(rows)

    if not agents:
        print("No agent data found \u2014 aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"Rendering charts for {len(agents)} agents\u2026")
    bar_b64   = make_stacked_bar(agents)
    donut_b64 = make_donut(agents)

    html = build_email_html(agents, args.company, date_label, args.company_id, bar_b64, donut_b64)

    with open(args.out, "w") as f:
        f.write(html)

    size_kb = len(html) / 1024
    print(f"Email HTML written to: {args.out} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
