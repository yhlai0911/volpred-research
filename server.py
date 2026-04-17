"""Minimal web server for Zeabur deployment.

Only needs: fastapi, uvicorn, python-multipart. No research packages.
"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="VolPred Web", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE = Path(__file__).parent
STORAGE = BASE / "storage"
MEMORY = STORAGE / "memory"
REPORTS = STORAGE / "reports"
PROJECT_TARGETS = BASE / "config" / "project_targets.json"


def _read_json(path: Path) -> list | dict:
    return json.loads(path.read_text()) if path.exists() else []


def _active_frontend_export_dir() -> Path | None:
    """Resolve the active frontend static export directory from project config."""
    try:
        payload = json.loads(PROJECT_TARGETS.read_text())
        active = payload.get("active_frontend")
        frontends = payload.get("frontends") or {}
        config = frontends.get(active) or {}
        rel_path = config.get("path")
        if not isinstance(rel_path, str) or not rel_path.strip():
            return None
        return BASE / rel_path / "out"
    except Exception:
        return None


# ========== API ==========

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}

@app.get("/api/publications/feed")
def get_feed(limit: int = 0):
    feed = _read_json(REPORTS / "feed.json")
    if isinstance(feed, list):
        feed.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return feed[:limit] if limit > 0 else feed

@app.get("/api/publications/feed/{pub_id}")
def get_publication(pub_id: str):
    feed = _read_json(REPORTS / "feed.json")
    for item in feed:
        if item.get("id") == pub_id:
            return item
    f = REPORTS / f"{pub_id}.json"
    if f.exists():
        return json.loads(f.read_text())
    raise HTTPException(404, "Not found")

class PublishRequest(BaseModel):
    title: str
    description: str = ""
    phase: str = ""
    details: dict = {}

@app.post("/api/publications/publish")
def publish(req: PublishRequest):
    import uuid
    REPORTS.mkdir(parents=True, exist_ok=True)
    pub_id = f"mile_{uuid.uuid4().hex[:8]}"
    item = {
        "id": pub_id, "title": req.title, "description": req.description,
        "category": "milestone", "phase": req.phase,
        "details": req.details, "published_at": datetime.now().isoformat(),
        "status": "published",
    }
    (REPORTS / f"{pub_id}.json").write_text(json.dumps(item, indent=2, ensure_ascii=False, default=str))
    feed = _read_json(REPORTS / "feed.json")
    feed.append(item)
    (REPORTS / "feed.json").write_text(json.dumps(feed, indent=2, ensure_ascii=False, default=str))
    return {"status": "published", "id": pub_id}

@app.get("/api/research/summary")
def summary():
    exps = _read_json(MEMORY / "experiments.json")
    log = _read_json(MEMORY / "research_log.json")
    knowledge = _read_json(MEMORY / "knowledge.json")
    assets = list(set(e.get("asset", "") for e in exps)) if isinstance(exps, list) else []
    scored = sorted(
        [e for e in exps if isinstance(e, dict) and e.get("metrics", {}).get("qlike", 0) < 0],
        key=lambda e: e["metrics"]["qlike"]
    )[:5]
    return {
        "n_experiments": len(exps), "n_log_entries": len(log),
        "n_knowledge_items": len(knowledge), "assets_studied": assets,
        "best_models": [{"experiment_id": e["experiment_id"], "model_name": e["model_name"],
                         "asset": e.get("asset", ""), "qlike": e["metrics"]["qlike"]} for e in scored],
    }

@app.get("/api/research/experiments")
def experiments():
    return _read_json(MEMORY / "experiments.json")

@app.get("/api/research/log")
def research_log():
    return _read_json(MEMORY / "research_log.json")

@app.get("/api/research/knowledge")
def knowledge():
    return _read_json(MEMORY / "knowledge.json")

@app.get("/api/research/thinking")
def thinking():
    return _read_json(MEMORY / "thinking_journal.json")

@app.get("/api/research/questions")
def questions():
    return _read_json(MEMORY / "open_questions.json")

@app.get("/api/research/paper-trading")
def paper_trading():
    return _read_json(STORAGE / "paper_trading.json")

@app.post("/api/sync/{file_path:path}")
def sync_file(file_path: str, data: dict | list):
    target = STORAGE / file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    return {"status": "synced", "path": file_path}

@app.get("/api/notifications")
def notifications():
    return _read_json(STORAGE / "notifications" / "notification_log.json")

@app.get("/api/risk-forecast")
def risk_forecast():
    return _read_json(STORAGE / "risk_forecast.json")


# ========== REPORT DETAIL (server-rendered, no Next.js) ==========

REPORT_PAGE = """<!DOCTYPE html>
<html lang="zh-Hant" class="dark"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VolPred Report</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" onload="renderMathInElement(document.getElementById('content'),{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}]})"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#030712;color:#f3f4f6;font-family:"Inter","Noto Sans TC",sans-serif;line-height:1.7}
.wrap{max-width:800px;margin:0 auto;padding:2rem 1rem}
a{color:#34d399;text-decoration:none}
h1{font-size:1.5rem;margin:1rem 0 0.5rem}
.badge{display:inline-block;font-size:0.7rem;padding:2px 10px;border-radius:99px;
  background:rgba(245,158,11,0.15);color:#fbbf24;border:1px solid rgba(245,158,11,0.3)}
.badge.member_qa{background:rgba(234,179,8,0.2);color:#facc15;border-color:rgba(234,179,8,0.5)}
.meta{color:#6b7280;font-size:0.8rem;margin:0.3rem 0 1rem}
.tags span{background:#1f2937;color:#9ca3af;font-size:0.7rem;padding:2px 8px;border-radius:4px;margin-right:4px}
.card{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:1.5rem;margin:1.5rem 0}
table{width:100%;border-collapse:collapse;font-size:0.85rem}
th{text-align:left;color:#6b7280;padding:8px;border-bottom:1px solid #1f2937}
td{padding:8px;border-bottom:1px solid rgba(31,41,55,0.5)}
.detail-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
.detail-item{background:rgba(31,41,55,0.5);padding:8px 12px;border-radius:8px}
.detail-key{font-size:0.7rem;color:#6b7280;text-transform:uppercase}
.detail-val{font-size:0.9rem;color:#d1d5db;font-family:monospace}
.desc{white-space:pre-wrap;font-size:0.9rem;color:#d1d5db}
</style>
</head><body><div class="wrap">
<p style="margin-bottom:1.5rem"><a href="/">← Research Feed</a></p>
<div id="content"><p style="color:#6b7280">載入中...</p></div>
<script>
var id=window.location.pathname.split("/").pop();
fetch("/api/publications/feed/"+id)
.then(function(r){if(!r.ok)throw new Error();return r.json()})
.then(function(d){
  var h='';
  var catLabel={member_qa:'會員提問'};
  if(d.category)h+='<span class="badge '+esc(d.category)+'">'+(catLabel[d.category]||esc(d.category))+'</span> ';
  if(d.published_at)h+='<span class="meta">'+esc(d.published_at.slice(0,19))+'</span>';
  h+='<h1>'+esc(d.title||'Report')+'</h1>';
  if(d.tags&&d.tags.length){h+='<div class="tags" style="margin:0.5rem 0">';d.tags.forEach(function(t){h+='<span>#'+esc(t)+'</span>'});h+='</div>'}
  if(d.ranking&&d.ranking.length){
    h+='<div class="card"><div style="font-weight:600;margin-bottom:0.8rem">排行榜</div><table><thead><tr>';
    var keys=Object.keys(d.ranking[0]);
    keys.forEach(function(k){h+='<th>'+esc(k)+'</th>'});
    h+='</tr></thead><tbody>';
    d.ranking.forEach(function(row,i){
      h+='<tr'+(i===0?' style="background:rgba(16,185,129,0.05)"':'')+'>';
      var medals=["🥇","🥈","🥉"];
      keys.forEach(function(k,j){
        var v=row[k];if(typeof v==='number')v=v.toFixed(4);
        if(k==='rank')v=medals[i]||v;
        h+='<td>'+esc(String(v))+'</td>'
      });
      h+='</tr>'
    });
    h+='</tbody></table></div>'
  }
  if(d.description||d.analysis){h+='<div class="card"><div class="desc">'+esc(d.description||d.analysis)+'</div></div>'}
  if(d.summary&&!d.description&&!d.analysis){h+='<div class="card"><div class="desc">'+esc(d.summary)+'</div></div>'}
  if(d.metrics){
    var mk=Object.keys(d.metrics).filter(function(k){return k!=='var_es'});
    if(mk.length){
      h+='<div class="card"><div style="font-weight:600;margin-bottom:0.8rem">指標</div><div class="detail-grid">';
      mk.forEach(function(k){
        var v=d.metrics[k];if(typeof v==='number')v=Math.abs(v)<0.001&&v!==0?v.toExponential(3):v.toFixed(4);
        h+='<div class="detail-item"><div class="detail-key">'+esc(k)+'</div><div class="detail-val">'+esc(String(v))+'</div></div>'
      });
      h+='</div></div>'
    }
  }
  if(d.details&&Object.keys(d.details).length){
    h+='<div class="card"><div style="font-weight:600;margin-bottom:0.8rem">詳情</div><div class="detail-grid">';
    Object.keys(d.details).forEach(function(k){
      var v=d.details[k];if(typeof v==='object')v=JSON.stringify(v);
      h+='<div class="detail-item"><div class="detail-key">'+esc(k)+'</div><div class="detail-val">'+esc(String(v))+'</div></div>'
    });
    h+='</div></div>'
  }
  h+='<p style="margin-top:2rem;font-size:0.75rem;color:#4b5563">ID: '+esc(d.id||id)+'</p>';
  document.getElementById("content").innerHTML=h
})
.catch(function(){document.getElementById("content").textContent="無法載入此報告"});
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML}
</script>
</div></body></html>"""


# ========== STATIC FRONTEND ==========

frontend = BASE / "static"  # On Zeabur: static/ alongside server.py
if not frontend.exists():
    active_export = _active_frontend_export_dir()
    if active_export is not None:
        frontend = active_export  # Local dev fallback to active frontend export

if frontend.exists():
    for subdir in ["_next", "data"]:
        p = frontend / subdir
        if p.exists():
            app.mount(f"/{subdir}", StaticFiles(directory=str(p)), name=f"static_{subdir}")

    @app.get("/reports/{report_id}")
    def report_page(report_id: str):
        return HTMLResponse(REPORT_PAGE)

    @app.get("/admin")
    def admin_page():
        return FileResponse(frontend / "admin.html", media_type="text/html")

    @app.get("/admin/{page}")
    def admin_subpage(page: str):
        f = frontend / "admin" / f"{page}.html"
        return FileResponse(f, media_type="text/html") if f.exists() else FileResponse(frontend / "404.html", status_code=404)

    @app.get("/risk-forecast")
    def risk_forecast_page():
        f = frontend / "risk-forecast.html"
        return FileResponse(f, media_type="text/html") if f.exists() else FileResponse(frontend / "index.html", media_type="text/html")

    @app.get("/")
    def index_page():
        return FileResponse(frontend / "index.html", media_type="text/html")
