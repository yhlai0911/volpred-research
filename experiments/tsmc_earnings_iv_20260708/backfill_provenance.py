"""Provenance backfill for tsmc_earnings_iv_20260708 (added 2026-07-09 by 24h paper_review).

原始 run 的文章引用了兩個數字 (rv5, earnings-day implied move) 但未存入 results JSON，
且原代碼未計算 rv5。此 reproducer 從可複現資料回填並記錄公式：
- rv5: 從價格史 (yfinance TSM, as-of 2026-07-08) 重算，公式同 rv20 (尾5日 logret std × √252)
- earnings_day_move: 從已 committed 的 IV 值 (front/back ATM IV, back days_to_exp) 推導，
  variance decomposition: move_E = √((IV_back² − IV_front²) × T_back/252)
Review 發現: 文章原寫 rv5=83%，但重算 ≈70% (13pp 不可複現) → 文章已更正。
"""
import yfinance as yf, numpy as np, json, pathlib

P = pathlib.Path("experiments/tsmc_earnings_iv_20260708/tsmc_earnings_iv_results.json")
d = json.loads(P.read_text())

# rv5 from reproducible price history (past prices are fixed; only options snapshot is point-in-time)
t = yf.Ticker("TSM"); h = t.history(period="2y"); h.index = h.index.tz_localize(None)
h = h.loc[h.index <= d["as_of"]]
lr = np.log(h["Close"]).diff().dropna()
rv5 = float(lr.tail(5).std()*np.sqrt(252)*100)

# earnings-day implied move from committed IVs (variance decomposition)
ivf = d["front_atm_iv_pct"]/100.0
ivb = d["back_atm_iv_pct"]/100.0
Tb = d["term_structure"][d["back_exp"]]["days_to_exp"]
move_e = float(np.sqrt(max(ivb**2 - ivf**2, 0.0)*(Tb/252))*100)

d["rv5_pct"] = round(rv5, 2)
d["earnings_day_implied_move_pct"] = round(move_e, 2)
d["provenance_backfill"] = {
    "added": "2026-07-09 (24h paper_review, task paper_review_mile_aee1c78c)",
    "rv5_formula": "tail(5) daily logret std * sqrt(252) * 100, as-of price history",
    "earnings_day_formula": "sqrt((IV_back^2 - IV_front^2) * days_back/252) * 100",
    "note": "文章原載 rv5=83%（不可複現，重算≈70%）已更正；earnings-day 4.0% 與重算一致。"
             " rv5 從價格史可複現（過去價格固定）；options 快照為 point-in-time 不可重跑。",
    "recompute_caveat": "重算 rv20=%.2f vs committed %.2f（yfinance 股息調整漂移 ~0.6pp）" % (
        float(lr.tail(20).std()*np.sqrt(252)*100), d["rv20_pct"]),
}
P.write_text(json.dumps(d, ensure_ascii=False, indent=2))
print(f"rv5={d['rv5_pct']}%  earnings_day_move={d['earnings_day_implied_move_pct']}%  backfilled OK")
