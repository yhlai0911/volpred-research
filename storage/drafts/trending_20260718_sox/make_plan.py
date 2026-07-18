import hashlib, json, pathlib

ROOT = pathlib.Path("/Users/yhlai0911/volpred-research")
ev_path = "experiments/trending_20260718_sox_capex/evidence.json"
sha = hashlib.sha256((ROOT / ev_path).read_bytes()).hexdigest()

def pct(digits=1, plus=False, absolute=False):
    return {"kind": "number", "digits": digits, "suffix": "%", "show_plus": plus, "absolute": absolute}
def num(digits=2, plus=False):
    return {"kind": "number", "digits": digits, "show_plus": plus}

E = "ev"
def val(path, fmt):
    return {"source": E, "path": path, "format": fmt}

plan = {
    "schema_version": 1,
    "title": "費半在修正，VIX 卻沒醒：三支溫度計，三個世界",
    "subtitle": "科技巨頭猛砸 AI capex，晶片股卻先回檔，避險工具別拿錯",
    "evidence": {E: {"path": ev_path, "sha256": sha, "label": "yfinance 收盤價與 SMH 選擇權隱含波動，截至 2026-07-17"}},
    "panels": [
        {
            "name": "01_thermometers",
            "info": "results",
            "style": "professional",
            "title": "同一場費半修正，三支波動率溫度計讀數差近三倍",
            "alt": "VIX、費半已實現波動、費半隱含波動三個讀數天差地遠",
            "sources": [E],
            "blocks": [
                {"kind": "metric", "label": "VIX（S&P 指數恐慌）", "value": val("vix.last", num(1)), "note": "還在平靜區間"},
                {"kind": "metric", "label": "費半已實現波動（SMH 近月，年化）", "value": val("realized_vol_20d.SMH.rv20_now_pct", pct(1)), "note": "近月單日一度近一成振幅"},
                {"kind": "metric", "label": "費半隱含波動（SMH 近月選擇權）", "value": val("smh_atm_iv_pct.value", pct(1)), "note": "市場已在幫這個 sector 定價"},
            ],
        },
        {
            "name": "02_concentrated",
            "info": "concept",
            "style": "editorial",
            "title": "痛點集中在費半，指數層級幾乎沒事",
            "alt": "SMH 自高點重挫，大盤只小跌，VIX 只微升",
            "sources": [E],
            "blocks": [
                {"kind": "metric", "label": "費半 SMH 自六月下旬高點回撤", "value": val("pullback.SMH.drawdown_from_peak_pct", pct(1, absolute=False)), "note": "同期 MTD 也接近雙位數"},
                {"kind": "metric", "label": "美股大盤 S&P 同期回撤", "value": val("pullback.^GSPC.drawdown_from_peak_pct", pct(1)), "note": "大盤基本沒被波及"},
                {"kind": "metric", "label": "VIX 六月中的起點水位", "value": val("vix.mid_june", num(1)), "note": "只多約兩點多，遠追不上費半跌幅"},
            ],
        },
        {
            "name": "03_takeaway",
            "info": "takeaway",
            "style": "scientific",
            "title": "避險工具要對準 sector，不是對準大盤",
            "alt": "VIX 對半導體曝險敏感度低，capex 與晶片股已脫鉤",
            "sources": [E],
            "blocks": [
                {"kind": "metric", "label": "SMH 與 VIX 近兩個月相關性", "value": val("correlation.smh_vs_vix_60d", num(2)), "note": "方向相反，但 VIX 幅度太小賠不夠"},
                {"kind": "metric", "label": "四大雲端巨頭與費半近兩個月相關性", "value": val("correlation.hyper_vs_sox_60d", num(2)), "note": "capex 敘事與晶片股已脫鉤"},
                {"kind": "text", "heading": "一句話帶走", "body": ["曝險集中在半導體，就用半導體自己的選擇權避險，別用只反映大盤情緒的 VIX。"]},
            ],
        },
    ],
}

out = ROOT / "storage/drafts/trending_20260718_sox/plan.json"
out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", out, "sha", sha[:12])
