#!/usr/bin/env python3
"""
build_email.py — Ultra-compact email-safe Agent Status Time Report.

No JS, no <style> blocks, all inline. Targets <25KB for 30 agents.
Removes redundant bar chart (table has all data). Minimal whitespace.
"""
import argparse, json, sys
from collections import defaultdict
from datetime import datetime

SM = {"0":("Offline","#94a3b8"),"1":("Available","#22c55e"),"2":("Busy","#f97316"),"3":("On Break","#eab308"),"4":("On Call","#3b82f6"),"5":("Wrap-Up","#a855f7"),"6":("Ringing","#06b6d4")}
VC = set(SM.keys())
DO = ["1","4","5","2","3","6","0"]
KO = ["1","4","5","2","3","0"]

def agg(rows):
    a = defaultdict(lambda:{c:0 for c in VC})
    for r in rows:
        n,c=r.get("agent_name","?"),str(r.get("status_code","0"))
        if c in VC: a[n][c]+=int(r.get("total_seconds",0) or 0)
    return dict(a)

def fh(s):
    if not s: return "\u2014"
    h,m,sc=s//3600,(s%3600)//60,s%60
    return f"{h}h {m}m" if h else (f"{m}m {sc}s" if m else f"{sc}s")

def fdl(s,e=None):
    try:
        d=datetime.strptime(s,"%Y-%m-%d")
        if not e or e==s: return d.strftime("%B %-d, %Y")
        d2=datetime.strptime(e,"%Y-%m-%d")
        if d.year!=d2.year: return f"{d.strftime('%B %-d, %Y')} \u2013 {d2.strftime('%B %-d, %Y')}"
        if d.month!=d2.month: return f"{d.strftime('%B %-d')} \u2013 {d2.strftime('%B %-d, %Y')}"
        return f"{d.strftime('%B %-d')}\u2013{d2.strftime('%-d, %Y')}"
    except: return e or s

def build_report(rows,co,sd,ed,cid,out):
    ag=agg(rows); dl=fdl(sd,ed)
    tot={c:0 for c in VC}
    for st in ag.values():
        for c,v in st.items(): tot[c]+=v
    gt=sum(tot.values()); nc=len(ag)

    # Sorted by On Call desc
    sa=sorted(ag.items(),key=lambda x:x[1].get("4",0),reverse=True)

    # Build table rows
    trows=""
    for nm,st in sa:
        t=sum(st.values()); act=sum(v for k,v in st.items() if k!="0")
        ap=f"{act/t*100:.0f}%" if t else "0%"
        r=f'<tr><td style="padding:5px 6px;font-weight:600;font-size:12px;border-bottom:1px solid #f0f0f0;">{nm}</td><td style="padding:5px 6px;font-size:12px;border-bottom:1px solid #f0f0f0;">{ap}</td>'
        for c in DO:
            v=st.get(c,0)
            cv=fh(v) if v else '<span style="color:#ccc;">\u2014</span>'
            r+=f'<td style="padding:5px 6px;font-size:12px;border-bottom:1px solid #f0f0f0;">{cv}</td>'
        trows+=r+"</tr>"

    # Table header
    hdr='<th style="padding:5px 6px;border-bottom:2px solid #ddd;font-size:10px;color:#6b7280;text-transform:uppercase;text-align:left;">Agent</th><th style="padding:5px 6px;border-bottom:2px solid #ddd;font-size:10px;color:#6b7280;text-transform:uppercase;text-align:left;">Active</th>'
    for c in DO:
        lb,cl=SM[c]
        hdr+=f'<th style="padding:5px 6px;border-bottom:2px solid #ddd;font-size:10px;color:{cl};text-transform:uppercase;text-align:left;">{lb}</th>'

    # KPI summary line
    kpis=""
    for c in KO:
        lb,cl=SM[c]; v=tot.get(c,0)
        p=f"{v/gt*100:.0f}%" if gt else "\u2014"
        kpis+=f'<td style="padding:8px 10px;text-align:center;"><div style="font-size:10px;color:#6b7280;text-transform:uppercase;">{lb}</div><div style="font-size:20px;font-weight:700;color:{cl};">{fh(v)}</div><div style="font-size:10px;color:#999;">{p}</div></td>'

    # Legend dots
    leg=""
    for c in DO:
        lb,cl=SM[c]
        leg+=f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{cl};margin:0 2px 0 8px;vertical-align:middle;"></span><span style="font-size:12px;vertical-align:middle;">{lb}</span>'

    h=f'<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;color:#1e2433;">'
    h+=f'<table cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:1000px;margin:0 auto;padding:10px;"><tr><td>'
    # Header
    h+=f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#1a2744;border-radius:8px;margin-bottom:10px;"><tr><td style="padding:16px 20px;"><div style="font-size:18px;font-weight:700;color:#fff;">Agent Status Time Report</div><div style="font-size:12px;color:rgba(255,255,255,.6);margin-top:2px;">{co} &middot; {nc} agents &middot; {dl}</div></td></tr></table>'
    # Legend
    h+=f'<div style="background:#fff;border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:0;"><span style="font-size:11px;color:#6b7280;font-weight:600;vertical-align:middle;">Status:</span>{leg}</div>'
    # KPIs
    h+=f'<table width="100%" cellpadding="0" cellspacing="4" border="0" style="background:#fff;border-radius:8px;margin-bottom:10px;"><tr>{kpis}</tr></table>'
    # Agent table
    h+=f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:8px;margin-bottom:10px;"><tr><td style="padding:12px 16px 4px;font-size:13px;font-weight:600;">Agent Breakdown \u2014 {dl}</td></tr><tr><td style="padding:4px 16px 12px;"><table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;"><thead><tr>{hdr}</tr></thead><tbody>{trows}</tbody></table></td></tr></table>'
    # Footer
    h+=f'<div style="text-align:center;font-size:10px;color:#999;padding:8px 0;">{dl} &middot; {co} (ID {cid}) &middot; LEAD() timestamp diff &middot; trailing offline excluded</div>'
    h+='</td></tr></table></body></html>'

    with open(out,"w") as f: f.write(h)
    print(f"Report: {out} ({nc} agents, {len(rows)} rows, {len(h)} bytes / {len(h)/1024:.1f}KB)")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",default=None); p.add_argument("--rows",default=None)
    p.add_argument("--company",default=None); p.add_argument("--start-date",default=None)
    p.add_argument("--end-date",default=None); p.add_argument("--company-id",type=int,default=0)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    if a.input:
        with open(a.input) as f: ct=json.load(f)
        m=ct.get("meta",{}); rows=ct.get("rows",[])
        co=m.get("company_name","?"); cid=m.get("company_id",0)
        dr=m.get("date_range",{}); sd=dr.get("start",""); ed=dr.get("end",sd)
    else:
        if not a.rows or not a.company or not a.start_date:
            print("ERROR",file=sys.stderr); sys.exit(1)
        rows=json.loads(a.rows); co=a.company; cid=a.company_id; sd=a.start_date; ed=a.end_date or sd
    if not rows: print("No rows.",file=sys.stderr); sys.exit(1)
    build_report(rows,co,sd,ed,cid,a.out)

if __name__=="__main__": main()
