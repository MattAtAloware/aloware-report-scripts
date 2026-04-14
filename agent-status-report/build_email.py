#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_email.py — Generate a deterministic Agent Status Time Report HTML file.

Produces a self-contained HTML dashboard with Chart.js charts rendered client-side.
The output is identical for the same input data on every run — no matplotlib, no
PIL, no non-deterministic image encoding.

Supports two input modes:
  --input  path/to/report_data.json   (data contract mode — preferred)
  --rows   '[{...}]' + --company + --start-date   (legacy CLI mode)

Data contract JSON schema:
  {
    "meta": {
      "company_name": "Debt Freedom USA",
      "company_id": 6364,
      "date_range": {"start": "2026-04-13", "end": "2026-04-13"}
    },
    "rows": [
      {"agent_name": "Ana Cruz", "status_code": "1", "total_seconds": 8435},
      ...
    ]
  }

Each row must have: agent_name (str), status_code (str "0"-"6"), total_seconds (int).
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime


# ── Data helpers ──────────────────────────────────────────────────────────────

def rows_to_raw_js(rows: list) -> str:
    """Convert query rows to the RAW JavaScript array string.

    Sums total_seconds across all rows for the same (agent_name, status_code)
    pair so multi-day ranges and multi-batch accumulation aggregate correctly.
    Filters out any non-numeric status codes (legacy values like "offline").
    """
    valid_codes = {"0", "1", "2", "3", "4", "5", "6"}
    agents: dict = defaultdict(lambda: {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0})
    for row in rows:
        name = row.get("agent_name", "Unknown")
        code = str(row.get("status_code", "0"))
        if code not in valid_codes:
            continue
        secs = int(row.get("total_seconds", 0) or 0)
        agents[name][code] += secs

    items = []
    for agent in sorted(agents.keys()):
        s = agents[agent]
        s_js = ", ".join(f'"{k}": {v}' for k, v in sorted(s.items()))
        items.append(f'  {{agent: "{agent}", s: {{{s_js}}}}}')
    return "[\n" + ",\n".join(items) + "\n]"


def format_date_label(start_str: str, end_str: str = None) -> str:
    """Format a date or date range as a human-readable label."""
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d")
        if not end_str or end_str == start_str:
            return start.strftime("%B %-d, %Y")
        end = datetime.strptime(end_str, "%Y-%m-%d")
        if start.year != end.year:
            return f"{start.strftime('%B %-d, %Y')} – {end.strftime('%B %-d, %Y')}"
        if start.month != end.month:
            return f"{start.strftime('%B %-d')} – {end.strftime('%B %-d, %Y')}"
        return f"{start.strftime('%B %-d')}–{end.strftime('%-d, %Y')}"
    except Exception:
        return end_str or start_str


# ── HTML Template (embedded) ─────────────────────────────────────────────────
# This is the canonical template. It uses Chart.js for client-side rendering,
# making the output fully deterministic — same input always produces same HTML.

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Status Time Report – {{COMPANY_NAME}}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1" integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" crossorigin="anonymous"></script>
  <style>
    :root {
      --bg: #f0f2f5; --card: #ffffff; --header: #1a2744; --accent: #2c5dbd;
      --text: #1e2433; --muted: #6b7280; --border: #e5e7eb; --gap: 16px; --radius: 10px;
      --available: #22c55e; --busy: #f97316; --on-break: #eab308;
      --on-call: #3b82f6; --wrap-up: #a855f7; --offline: #94a3b8; --ringing: #06b6d4;
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:var(--bg); color:var(--text); }
    .wrap { max-width:1400px; margin:0 auto; padding:var(--gap); }
    .header { background:var(--header); color:#fff; border-radius:var(--radius); padding:20px 28px; margin-bottom:var(--gap); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }
    .header-left h1 { font-size:20px; font-weight:700; }
    .header-left p  { font-size:13px; color:rgba(255,255,255,.65); margin-top:3px; }
    .header-right   { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    .filter-group   { display:flex; flex-direction:column; gap:3px; }
    .filter-group label { font-size:11px; color:rgba(255,255,255,.6); text-transform:uppercase; letter-spacing:.5px; }
    .filter-group select { padding:6px 10px; border-radius:6px; background:rgba(255,255,255,.12); color:#fff; border:1px solid rgba(255,255,255,.25); font-size:13px; cursor:pointer; }
    .filter-group select option { background:#1a2744; }
    .legend-bar { background:var(--card); border-radius:var(--radius); padding:12px 20px; margin-bottom:var(--gap); display:flex; gap:20px; flex-wrap:wrap; align-items:center; box-shadow:0 1px 3px rgba(0,0,0,.07); }
    .legend-bar span { font-size:12px; color:var(--muted); font-weight:600; margin-right:4px; }
    .legend-item { display:flex; align-items:center; gap:6px; font-size:13px; }
    .legend-dot  { width:12px; height:12px; border-radius:3px; flex-shrink:0; }
    .kpi-row { display:grid; grid-template-columns:repeat(auto-fit, minmax(160px,1fr)); gap:var(--gap); margin-bottom:var(--gap); }
    .kpi-card { background:var(--card); border-radius:var(--radius); padding:18px 20px; box-shadow:0 1px 3px rgba(0,0,0,.07); border-top:3px solid transparent; }
    .kpi-card.available { border-color:var(--available); } .kpi-card.on-call { border-color:var(--on-call); }
    .kpi-card.busy { border-color:var(--busy); } .kpi-card.on-break { border-color:var(--on-break); }
    .kpi-card.wrap-up { border-color:var(--wrap-up); } .kpi-card.offline { border-color:var(--offline); }
    .kpi-label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; margin-bottom:4px; }
    .kpi-value { font-size:26px; font-weight:700; }
    .kpi-sub   { font-size:12px; color:var(--muted); margin-top:2px; }
    .chart-row { display:grid; grid-template-columns:2fr 1fr; gap:var(--gap); margin-bottom:var(--gap); }
    .chart-card { background:var(--card); border-radius:var(--radius); padding:20px 24px; box-shadow:0 1px 3px rgba(0,0,0,.07); }
    .chart-card h3 { font-size:14px; font-weight:600; margin-bottom:16px; }
    #stackedChart { max-height:780px; } #donutChart { max-height:340px; }
    .table-card { background:var(--card); border-radius:var(--radius); padding:20px 24px; box-shadow:0 1px 3px rgba(0,0,0,.07); overflow-x:auto; }
    .table-card h3 { font-size:14px; font-weight:600; margin-bottom:14px; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    thead th { text-align:left; padding:9px 12px; border-bottom:2px solid var(--border); color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.5px; cursor:pointer; white-space:nowrap; user-select:none; }
    thead th:hover { color:var(--text); }
    tbody td { padding:9px 12px; border-bottom:1px solid #f3f4f6; }
    tbody tr:last-child td { border-bottom:none; }
    tbody tr:hover { background:#f9fafb; }
    .bar-bg   { background:#f1f5f9; border-radius:4px; height:8px; min-width:60px; overflow:hidden; }
    .bar-fill { height:100%; border-radius:4px; }
    footer { text-align:center; font-size:12px; color:var(--muted); padding:16px 0 8px; }
    @media(max-width:900px) { .chart-row { grid-template-columns:1fr; } }
    @media(max-width:600px) { .kpi-row  { grid-template-columns:repeat(2,1fr); } }
  </style>
</head>
<body>
<div class="wrap">

  <div class="header">
    <div class="header-left">
      <h1>Agent Status Time Report</h1>
      <p id="subtitle">{{COMPANY_NAME}} · {{REPORT_DATE_LABEL}}</p>
    </div>
    <div class="header-right">
      <div class="filter-group">
        <label>Agent</label>
        <select id="agentFilter" onchange="applyFilter()">
          <option value="all">All Agents</option>
        </select>
      </div>
    </div>
  </div>

  <div class="legend-bar">
    <span>Status Key:</span>
    <div class="legend-item"><div class="legend-dot" style="background:var(--available)"></div> Available</div>
    <div class="legend-item"><div class="legend-dot" style="background:var(--on-call)"></div> On Call</div>
    <div class="legend-item"><div class="legend-dot" style="background:var(--wrap-up)"></div> Wrap-Up</div>
    <div class="legend-item"><div class="legend-dot" style="background:var(--busy)"></div> Busy</div>
    <div class="legend-item"><div class="legend-dot" style="background:var(--on-break)"></div> On Break</div>
    <div class="legend-item"><div class="legend-dot" style="background:var(--ringing)"></div> Ringing</div>
    <div class="legend-item"><div class="legend-dot" style="background:var(--offline)"></div> Offline</div>
  </div>

  <div class="kpi-row">
    <div class="kpi-card available"><div class="kpi-label">Available</div><div class="kpi-value" id="kpi-1">—</div><div class="kpi-sub" id="kpi-1-pct"></div></div>
    <div class="kpi-card on-call">  <div class="kpi-label">On Call</div>  <div class="kpi-value" id="kpi-4">—</div><div class="kpi-sub" id="kpi-4-pct"></div></div>
    <div class="kpi-card wrap-up">  <div class="kpi-label">Wrap-Up</div>  <div class="kpi-value" id="kpi-5">—</div><div class="kpi-sub" id="kpi-5-pct"></div></div>
    <div class="kpi-card busy">     <div class="kpi-label">Busy</div>      <div class="kpi-value" id="kpi-2">—</div><div class="kpi-sub" id="kpi-2-pct"></div></div>
    <div class="kpi-card on-break"> <div class="kpi-label">On Break</div>  <div class="kpi-value" id="kpi-3">—</div><div class="kpi-sub" id="kpi-3-pct"></div></div>
    <div class="kpi-card offline">  <div class="kpi-label">Offline</div>   <div class="kpi-value" id="kpi-0">—</div><div class="kpi-sub" id="kpi-0-pct"></div></div>
  </div>

  <div class="chart-row">
    <div class="chart-card">
      <h3>Time in Each Status per Agent (hours) — sorted by On Call + Available</h3>
      <canvas id="stackedChart"></canvas>
    </div>
    <div class="chart-card">
      <h3>Team-Wide Status Distribution</h3>
      <canvas id="donutChart"></canvas>
    </div>
  </div>

  <div class="table-card">
    <h3 id="tableTitle">Agent Status Breakdown — {{REPORT_DATE_LABEL}}</h3>
    <table>
      <thead>
        <tr>
          <th onclick="sortTable('agent')">Agent ↕</th>
          <th onclick="sortTable('active_pct')">Active % ↕</th>
          <th onclick="sortTable('s1')" style="color:var(--available)">Available ↕</th>
          <th onclick="sortTable('s4')" style="color:var(--on-call)">On Call ↕</th>
          <th onclick="sortTable('s5')" style="color:var(--wrap-up)">Wrap-Up ↕</th>
          <th onclick="sortTable('s2')" style="color:var(--busy)">Busy ↕</th>
          <th onclick="sortTable('s3')" style="color:var(--on-break)">On Break ↕</th>
          <th onclick="sortTable('s6')" style="color:var(--ringing)">Ringing ↕</th>
          <th onclick="sortTable('s0')" style="color:var(--offline)">Offline ↕</th>
        </tr>
      </thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>

  <footer>Data for {{REPORT_DATE_LABEL}} · {{COMPANY_NAME}} (ID {{COMPANY_ID}}) · Source: Aloware agent_audits · Method: LEAD() timestamp diff; trailing offline after last logout excluded</footer>
</div>

<script>
const RAW = {{RAW_DATA_JS}};

const STATUS_LABELS = {"0":"Offline","1":"Available","2":"Busy","3":"On Break","4":"On Call","5":"Wrap-Up","6":"Ringing"};
const STATUS_COLORS = {"0":"#94a3b8","1":"#22c55e","2":"#f97316","3":"#eab308","4":"#3b82f6","5":"#a855f7","6":"#06b6d4"};
const COMPANY_NAME  = "{{COMPANY_NAME}}";
const REPORT_DATE   = "{{REPORT_DATE_LABEL}}";

function fmtHMS(secs) {
  if (!secs) return '—';
  const h = Math.floor(secs/3600), m = Math.floor((secs%3600)/60), s = secs%60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
function toHrs(secs) { return (secs/3600).toFixed(2); }

let activeAgent = 'all';
let stackedChart, donutChart;

window.addEventListener('DOMContentLoaded', () => { populateFilter(); render(); });

function populateFilter() {
  const sel = document.getElementById('agentFilter');
  [...RAW].sort((a,b)=>a.agent.localeCompare(b.agent)).forEach(r => {
    const o = document.createElement('option'); o.value = r.agent; o.textContent = r.agent; sel.appendChild(o);
  });
}
function applyFilter() { activeAgent = document.getElementById('agentFilter').value; render(); }
function filteredData() { return activeAgent === 'all' ? RAW : RAW.filter(r => r.agent === activeAgent); }

function totals(data) {
  const t = {"0":0,"1":0,"2":0,"3":0,"4":0,"5":0,"6":0};
  data.forEach(r => Object.keys(r.s).forEach(k => t[k] += (r.s[k]||0)));
  return t;
}

function render() {
  const data = filteredData();
  updateSubtitle(data);
  updateKPIs(data);
  updateStacked(data);
  updateDonut(data);
  renderTable(data);
}

function updateSubtitle(data) {
  const lbl = activeAgent === 'all' ? `${data.length} agents · ${REPORT_DATE}` : `${activeAgent} · ${REPORT_DATE}`;
  document.getElementById('subtitle').textContent = `${COMPANY_NAME}  ·  ${lbl}`;
}

function updateKPIs(data) {
  const t = totals(data);
  const grand = Object.values(t).reduce((a,b)=>a+b,0);
  const pct = v => grand ? ((v/grand)*100).toFixed(1)+'%' : '—';
  ["0","1","2","3","4","5"].forEach(k => {
    document.getElementById(`kpi-${k}`).textContent = fmtHMS(t[k]);
    document.getElementById(`kpi-${k}-pct`).textContent = `${pct(t[k])} of total`;
  });
}

function updateStacked(data) {
  const active = [...data].sort((a,b) => (b.s["4"]+b.s["1"]) - (a.s["4"]+a.s["1"]));
  const labels = active.map(r => r.agent);
  const order = ["1","4","5","2","3","6","0"];
  const datasets = order.map(sc => ({
    label: STATUS_LABELS[sc],
    data: active.map(r => parseFloat(toHrs(r.s[sc]||0))),
    backgroundColor: STATUS_COLORS[sc] + 'dd',
    borderColor: STATUS_COLORS[sc],
    borderWidth: 0.5,
    borderRadius: 2,
  }));
  const ctx = document.getElementById('stackedChart').getContext('2d');
  if (stackedChart) {
    stackedChart.data.labels = labels;
    stackedChart.data.datasets = datasets;
    stackedChart.update('none');
  } else {
    stackedChart = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${fmtHMS(Math.round(ctx.parsed.x*3600))}` } }
        },
        scales: {
          x: { stacked: true, ticks: { callback: v => `${v}h` }, grid: { color:'#f0f0f0' } },
          y: { stacked: true, ticks: { font: { size:12 } }, grid: { display:false } }
        }
      }
    });
  }
}

function updateDonut(data) {
  const t = totals(data);
  const order = ["1","4","5","2","3","6","0"];
  const ctx = document.getElementById('donutChart').getContext('2d');
  if (donutChart) {
    donutChart.data.datasets[0].data = order.map(k=>t[k]);
    donutChart.update('none');
  } else {
    donutChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: order.map(k=>STATUS_LABELS[k]),
        datasets: [{ data: order.map(k=>t[k]), backgroundColor: order.map(k=>STATUS_COLORS[k]+'ee'), borderColor:'#fff', borderWidth:2 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout:'58%',
        plugins: {
          legend: { position:'bottom', labels:{ usePointStyle:true, padding:14, font:{size:12} } },
          tooltip: {
            callbacks: {
              label: ctx => {
                const total = ctx.dataset.data.reduce((a,b)=>a+b,0);
                const pct = total ? ((ctx.parsed/total)*100).toFixed(1) : 0;
                return ` ${ctx.label}: ${fmtHMS(ctx.parsed)} (${pct}%)`;
              }
            }
          }
        }
      }
    });
  }
}

let _sortKey = 's4', _sortDir = -1;
function sortTable(key) {
  if (_sortKey === key) _sortDir *= -1; else { _sortKey = key; _sortDir = -1; }
  renderTable(filteredData());
}

function renderTable(data) {
  const getV = (r, k) => {
    if (k === 'agent') return r.agent;
    if (k === 'active_pct') {
      const act = Object.entries(r.s).filter(([c])=>c!=="0").reduce((a,[,v])=>a+v,0);
      const tot = act + (r.s["0"]||0);
      return tot ? act/tot : 0;
    }
    return r.s[k.replace('s','')]||0;
  };
  const sorted = [...data].sort((a,b) => {
    const av = getV(a,_sortKey), bv = getV(b,_sortKey);
    return typeof av==='string' ? _sortDir*av.localeCompare(bv) : _sortDir*(bv-av);
  });
  document.getElementById('tableBody').innerHTML = sorted.map(r => {
    const act = Object.entries(r.s).filter(([c])=>c!=="0").reduce((a,[,v])=>a+v,0);
    const tot = act + (r.s["0"]||0);
    const pct = tot ? ((act/tot)*100).toFixed(1) : '0.0';
    const cell = (k) => r.s[k] ? fmtHMS(r.s[k]) : '<span style="color:#d1d5db">—</span>';
    return `<tr>
      <td><strong>${r.agent}</strong></td>
      <td>
        <div style="display:flex;align-items:center;gap:6px">
          <div class="bar-bg" style="width:60px"><div class="bar-fill" style="width:${pct}%;background:var(--accent)"></div></div>
          <span style="font-size:12px;font-weight:600">${pct}%</span>
        </div>
      </td>
      <td>${cell("1")}</td>
      <td>${cell("4")}</td>
      <td>${cell("5")}</td>
      <td>${cell("2")}</td>
      <td>${cell("3")}</td>
      <td>${cell("6")}</td>
      <td>${cell("0")}</td>
    </tr>`;
  }).join('');
}
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def build_report(rows, company, start_date, end_date, company_id, out_path):
    """Build the HTML report from rows and write to out_path."""
    raw_js = rows_to_raw_js(rows)
    date_label = format_date_label(start_date, end_date)

    html = (HTML_TEMPLATE
            .replace("{{COMPANY_NAME}}", company)
            .replace("{{REPORT_DATE_LABEL}}", date_label)
            .replace("{{COMPANY_ID}}", str(company_id))
            .replace("{{RAW_DATA_JS}}", raw_js))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Count agents for confirmation
    valid_codes = {"0", "1", "2", "3", "4", "5", "6"}
    agents = set()
    for row in rows:
        code = str(row.get("status_code", "0"))
        if code in valid_codes:
            agents.add(row.get("agent_name", "Unknown"))

    print(f"Report written to: {out_path} ({len(agents)} agents, {len(rows)} rows)")


def main():
    parser = argparse.ArgumentParser(description="Build Agent Status Time Report HTML")
    parser.add_argument("--input",      default=None, help="Path to data contract JSON file")
    parser.add_argument("--rows",       default=None, help="JSON array of query result rows (legacy mode)")
    parser.add_argument("--company",    default=None, help="Company name (legacy mode)")
    parser.add_argument("--start-date", default=None, help="Report start date YYYY-MM-DD")
    parser.add_argument("--end-date",   default=None, help="Report end date YYYY-MM-DD (defaults to start-date)")
    parser.add_argument("--company-id", type=int, default=0, help="Aloware company ID")
    parser.add_argument("--out",        required=True, help="Output HTML file path")
    args = parser.parse_args()

    if args.input:
        # Data contract mode
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
        # Legacy CLI mode
        if not args.rows or not args.company or not args.start_date:
            print("ERROR: must provide --input or (--rows + --company + --start-date)", file=sys.stderr)
            sys.exit(1)
        rows       = json.loads(args.rows)
        company    = args.company
        company_id = args.company_id
        start_date = args.start_date
        end_date   = args.end_date or args.start_date

    if not rows:
        print("No rows provided — aborting.", file=sys.stderr)
        sys.exit(1)

    build_report(rows, company, start_date, end_date, company_id, args.out)


if __name__ == "__main__":
    main()
