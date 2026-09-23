from __future__ import annotations

import argparse
import ipaddress
import json
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .db import connect, db_path, project_root, today

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>agent-ledger</title><style>
:root{color-scheme:dark;--bg:#080b10;--panel:#111720;--line:#24303d;--muted:#8c9aaa;--text:#edf3f8;--lime:#a9e34b;--blue:#66b3ff;--amber:#ffc857;--red:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#152231 0,transparent 34%),var(--bg);color:var(--text);font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
main{max-width:1440px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;align-items:end;margin-bottom:22px}h1{font-size:26px;margin:0;letter-spacing:-1px}.eyebrow,.muted{color:var(--muted)}.eyebrow{text-transform:uppercase;letter-spacing:2px;font-size:11px}.stamp{text-align:right}.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px}.kpi,.panel{background:color-mix(in srgb,var(--panel) 92%,transparent);border:1px solid var(--line);border-radius:12px}.kpi{padding:14px}.kpi b{font:700 24px/1.2 system-ui}.kpi span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;margin-top:5px}.grid{display:grid;grid-template-columns:1.15fr 1fr .9fr;gap:14px}.panel{padding:16px;min-width:0}.panel h2{font:650 15px system-ui;margin:0 0 12px}.wide{grid-column:span 2}.row{padding:11px 0;border-top:1px solid var(--line)}.row:first-of-type{border-top:0}.rowhead{display:flex;gap:8px;align-items:center;justify-content:space-between}.title{font-weight:700}.pill{border:1px solid var(--line);border-radius:999px;padding:2px 7px;color:var(--muted);font-size:11px}.Doing,.worker{color:var(--lime)}.Blocked{color:var(--red)}.Ready,.planner{color:var(--blue)}.consult{color:var(--amber)}button.card{all:unset;display:block;width:100%;cursor:pointer}.feed{max-height:460px;overflow:auto}.feed time{color:var(--muted);font-size:11px}.empty{color:var(--muted);padding:8px 0}.progress{margin-top:5px;color:#c4ced8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}dialog{width:min(760px,calc(100% - 24px));max-height:85vh;overflow:auto;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:14px;padding:22px}dialog::backdrop{background:#000b}dialog button{float:right;background:none;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:5px 9px}.detail-block{white-space:pre-wrap;background:#0b1017;border-radius:8px;padding:11px;margin:9px 0}a{color:var(--blue)}
@media(max-width:1000px){.kpis{grid-template-columns:repeat(3,1fr)}.grid{grid-template-columns:1fr 1fr}.wide{grid-column:span 2}}@media(max-width:650px){main{padding:16px}.top{align-items:start}.stamp{font-size:11px}.kpis{grid-template-columns:repeat(2,1fr)}.grid{display:block}.panel{margin-bottom:12px}.wide{grid-column:auto}}
</style></head><body><main>
<div class="top"><div><div class="eyebrow">local coordination</div><h1>agent-ledger</h1></div><div class="stamp muted" id="stamp">loading</div></div>
<section class="kpis" id="kpis"></section><section class="grid">
<div class="panel"><h2>Sessions</h2><div id="sessions"></div></div>
<div class="panel"><h2>Today's plan</h2><div id="plan"></div></div>
<div class="panel"><h2>Open decisions</h2><div id="decisions"></div></div>
<div class="panel wide"><h2>Active cards</h2><div id="cards"></div></div>
<div class="panel"><h2>Activity</h2><div class="feed" id="feed"></div></div>
</section></main><dialog id="detail"><button onclick="detail.close()">Close</button><div id="detailBody"></div></dialog>
<script>
const el=id=>document.getElementById(id), esc=s=>String(s??'');
function empty(id,text){el(id).innerHTML='';let d=document.createElement('div');d.className='empty';d.textContent=text;el(id).append(d)}
function row(parent, parts){let d=document.createElement('div');d.className='row';parts(d);parent.append(d)}
async function cardDetail(id){let data=await fetch('/api/card?id='+encodeURIComponent(id)).then(r=>r.json());el('detailBody').innerHTML='';let h=document.createElement('h2');h.textContent=data.id+' · '+data.title;el('detailBody').append(h);['lane','status','owner','progress'].forEach(k=>{let d=document.createElement('div');d.className='detail-block';d.textContent=k.toUpperCase()+'\n'+(data[k]||'-');el('detailBody').append(d)});for(const group of ['decisions','notes','changes']){let h3=document.createElement('h3');h3.textContent=group;el('detailBody').append(h3);for(const item of data[group]){let d=document.createElement('div');d.className='row';d.textContent=item.body||((item.field||'')+': '+(item.new_value||'-'));el('detailBody').append(d)}}detail.showModal()}
async function load(){let d=await fetch('/api/snapshot').then(r=>r.json());el('stamp').textContent=d.now;let ks=[['planner','planners'],['consult','consults'],['worker','workers'],['active_cards','active cards'],['open_decisions','open decisions'],['unread','unread']];el('kpis').innerHTML='';for(const [k,label] of ks){let x=document.createElement('div');x.className='kpi';let b=document.createElement('b');b.textContent=d.counts[k]||0;let s=document.createElement('span');s.textContent=label;x.append(b,s);el('kpis').append(x)}
el('sessions').innerHTML='';if(!d.sessions.length)empty('sessions','No active sessions.');for(const s of d.sessions)row(el('sessions'),x=>{x.innerHTML='<div class="rowhead"><span class="title '+s.role+'"></span><span class="pill"></span></div><div class="muted"></div>';x.querySelector('.title').textContent=s.role||'unregistered';x.querySelector('.pill').textContent=s.tag;x.querySelector('.muted').textContent='pid '+(s.pid||'-')+' · '+s.started_at});
el('plan').innerHTML='';if(!d.plan.length)empty('plan','No cards planned today.');for(const c of d.plan)row(el('plan'),x=>{x.textContent=c.id+' · '+c.title});
el('decisions').innerHTML='';if(!d.decisions.length)empty('decisions','No open decisions.');for(const q of d.decisions)row(el('decisions'),x=>{x.innerHTML='<div class="rowhead"><span class="title"></span><span class="pill"></span></div><div class="muted"></div>';x.querySelector('.title').textContent='#'+q.id;x.querySelector('.pill').textContent=q.card_id||'general';x.querySelector('.muted').textContent=q.body});
el('cards').innerHTML='';if(!d.cards.length)empty('cards','No active cards.');for(const c of d.cards)row(el('cards'),x=>{let b=document.createElement('button');b.className='card';b.onclick=()=>cardDetail(c.id);b.innerHTML='<div class="rowhead"><span class="title"></span><span class="pill"></span></div><div class="progress"></div>';b.querySelector('.title').textContent=c.id+' · '+c.title;b.querySelector('.pill').textContent=c.lane+' / '+c.status;b.querySelector('.progress').textContent=(c.owner?'owner '+c.owner+' · ':'')+(c.progress||'No progress update');x.append(b)});
el('feed').innerHTML='';if(!d.feed.length)empty('feed','No activity yet.');for(const f of d.feed)row(el('feed'),x=>{let t=document.createElement('time');t.textContent=f.created_at+' · '+f.session;let p=document.createElement('div');p.textContent=f.label;x.append(t,p)});}
load();setInterval(load,4000);
</script></body></html>"""


def validate_bind(host: str, unsafe_expose: bool = False) -> None:
    if unsafe_expose:
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        if host.lower() == "localhost":
            return
    raise ValueError("Refusing non-loopback binding without --unsafe-expose; the dashboard has no authentication.")


def snapshot(root: Path) -> dict:
    with connect(root, create=False, readonly=True) as con:
        sessions = [dict(row) for row in con.execute(
            "SELECT tag,role,pid,started_at FROM sessions WHERE ended_at IS NULL ORDER BY started_at"
        )]
        cards = [dict(row) for row in con.execute(
            "SELECT id,title,lane,status,progress,owner,updated_at FROM cards WHERE closed_at IS NULL "
            "ORDER BY CASE lane WHEN 'Doing' THEN 0 WHEN 'Blocked' THEN 1 WHEN 'Ready' THEN 2 ELSE 3 END,updated_at DESC"
        )]
        decisions = [dict(row) for row in con.execute(
            "SELECT id,card_id,body,raised_by,created_at FROM decisions WHERE closed_at IS NULL ORDER BY id"
        )]
        plan = [dict(row) for row in con.execute(
            "SELECT c.id,c.title,c.status FROM day_plan p JOIN cards c ON c.id=p.card_id "
            "WHERE p.day=? AND p.removed_at IS NULL ORDER BY p.added_at", (today(),)
        )]
        feed = [dict(row) for row in con.execute(
            "SELECT created_at,session,table_name||'/'||row_id||' '||field AS label "
            "FROM changelog ORDER BY id DESC LIMIT 50"
        )]
        counts = {role: sum(1 for item in sessions if item["role"] == role) for role in ("planner", "consult", "worker")}
        counts.update({
            "active_cards": len(cards),
            "open_decisions": len(decisions),
            "unread": con.execute("SELECT COUNT(*) FROM inbox WHERE read_at IS NULL").fetchone()[0],
        })
    import datetime as dt
    return {"now": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "counts": counts,
            "sessions": sessions, "cards": cards, "decisions": decisions, "plan": plan, "feed": feed}


def card_detail(root: Path, card_id: str) -> dict | None:
    with connect(root, create=False, readonly=True) as con:
        card = con.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not card:
            return None
        result = dict(card)
        result["decisions"] = [dict(row) for row in con.execute(
            "SELECT body,created_at,resolution FROM decisions WHERE card_id=? ORDER BY id", (card_id,)
        )]
        result["notes"] = [dict(row) for row in con.execute(
            "SELECT body,created_at,session FROM notes WHERE card_id=? ORDER BY id DESC", (card_id,)
        )]
        result["changes"] = [dict(row) for row in con.execute(
            "SELECT field,new_value,created_at,session FROM changelog WHERE table_name='cards' AND row_id=? ORDER BY id DESC",
            (card_id,),
        )]
        return result


def handler(root: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            try:
                if parsed.path == "/":
                    self.send(PAGE.encode(), "text/html; charset=utf-8")
                elif parsed.path == "/api/snapshot":
                    self.send(json.dumps(snapshot(root)).encode(), "application/json")
                elif parsed.path == "/api/card":
                    card_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
                    data = card_detail(root, card_id)
                    self.send(json.dumps(data or {"error": "not found"}).encode(), "application/json", 200 if data else 404)
                else:
                    self.send(b"not found", "text/plain", 404)
            except (OSError, sqlite3.Error) as exc:
                self.send(json.dumps({"error": str(exc)}).encode(), "application/json", 500)

        def send(self, body: bytes, content_type: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent-ledger-dashboard", description="Run the read-only local dashboard.")
    p.add_argument("--project", type=Path)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--unsafe-expose", action="store_true")
    args = p.parse_args(argv)
    try:
        validate_bind(args.host, args.unsafe_expose)
        root = project_root(args.project) if args.project else project_root()
        if not db_path(root).exists():
            raise ValueError(f"Ledger not found. Run `agent-ledger init` in {root} first.")
    except ValueError as exc:
        p.error(str(exc))
    server = ThreadingHTTPServer((args.host, args.port), handler(root))
    print(f"agent-ledger dashboard: http://{args.host}:{args.port}")
    print("Read-only, no authentication. Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
