"""TSMC (TSM ADR) 法說會前隱含波動率定價 evidence package.
Earnings: 2026-07-16 (Q2 2026 conf call, Taiwan 14:00). Quiet period Jul 6-15.
Data: yfinance TSM ADR options + price history. As-of 2026-07-08.
No lookahead: all IV/price snapshots are same-day observations; historical
earnings moves use realized close-to-close around each past earnings date.
"""
import yfinance as yf
import numpy as np, pandas as pd, json, datetime as dt

EARN = "2026-07-16"
t = yf.Ticker("TSM")
spot = float(t.history(period="1d")["Close"].iloc[-1])
hist = t.history(period="2y")
hist.index = hist.index.tz_localize(None)
logret = np.log(hist["Close"]).diff().dropna()
rv20 = float(logret.tail(20).std()*np.sqrt(252)*100)
rv60 = float(logret.tail(60).std()*np.sqrt(252)*100)

def atm_iv(exp):
    ch = t.option_chain(exp)
    c, p = ch.calls.copy(), ch.puts.copy()
    c["d"]=(c.strike-spot).abs(); p["d"]=(p.strike-spot).abs()
    ac, ap = c.sort_values("d").iloc[0], p.sort_values("d").iloc[0]
    iv = float(np.nanmean([ac.impliedVolatility, ap.impliedVolatility]))
    # ATM straddle mid for implied move
    def mid(row): 
        b,a = row.get("bid",np.nan), row.get("ask",np.nan)
        return (b+a)/2 if (b and a and not np.isnan(b) and not np.isnan(a) and b>0) else row.get("lastPrice",np.nan)
    straddle = mid(ac)+mid(ap)
    return iv, ac.strike, float(straddle), ap.strike

term = {}
for e in t.options:
    try:
        iv, ks, straddle, kp = atm_iv(e)
        days = (dt.date.fromisoformat(e)-dt.date.fromisoformat("2026-07-08")).days
        term[e] = {"days_to_exp": days, "atm_iv_pct": round(iv*100,2),
                   "spans_earnings": e >= EARN and days>0,
                   "atm_straddle": round(straddle,2),
                   "implied_move_pct": round(straddle/spot*100,2)}
    except Exception as ex:
        term[e] = {"error": str(ex)}

# 25-delta-ish skew on back expiry (spans earnings): OTM put vs OTM call ~5% away
def skew(exp, pct=0.05):
    ch = t.option_chain(exp)
    c, p = ch.calls.copy(), ch.puts.copy()
    kc, kp = spot*(1+pct), spot*(1-pct)
    c["d"]=(c.strike-kc).abs(); p["d"]=(p.strike-kp).abs()
    ivc = float(c.sort_values("d").iloc[0].impliedVolatility)
    ivp = float(p.sort_values("d").iloc[0].impliedVolatility)
    return round(ivp*100,2), round(ivc*100,2), round((ivp-ivc)*100,2)

back_exp = sorted([e for e in t.options if e>=EARN])[0]
front_exp = sorted([e for e in t.options if e<EARN])[-1]
ivp5, ivc5, sk5 = skew(back_exp)

# Historical earnings-day realized moves (TSMC reports ~mid Jan/Apr/Jul/Oct)
# Approximate quarterly earnings dates; use largest |1d move| in each earnings window
earn_hist_dates = ["2024-01-18","2024-04-18","2024-07-18","2024-10-17",
                   "2025-01-16","2025-04-17","2025-07-17","2025-10-16","2026-01-15","2026-04-16"]
moves=[]
for d in earn_hist_dates:
    dd = pd.Timestamp(d)
    win = hist.loc[(hist.index>=dd-pd.Timedelta(days=3))&(hist.index<=dd+pd.Timedelta(days=3))]
    if len(win)>=2:
        r = np.log(win["Close"]).diff().dropna()
        if len(r): moves.append(abs(r).max()*100)
avg_earn_move = round(float(np.mean(moves)),2) if moves else None
med_earn_move = round(float(np.median(moves)),2) if moves else None

back_iv = term[back_exp]["atm_iv_pct"]; front_iv = term[front_exp]["atm_iv_pct"]
implied_move_back = term[back_exp]["implied_move_pct"]

out = {
  "as_of":"2026-07-08","ticker":"TSM (TSMC ADR)","earnings_date":EARN,
  "quiet_period":"2026-07-06 to 2026-07-15","spot":round(spot,2),
  "rv20_pct":round(rv20,2),"rv60_pct":round(rv60,2),
  "front_exp":front_exp,"front_atm_iv_pct":front_iv,
  "back_exp":back_exp,"back_atm_iv_pct":back_iv,
  "earnings_vol_premium_pp":round(back_iv-front_iv,2),
  "back_implied_move_pct":implied_move_back,
  "iv_rv_gap_back_pp":round(back_iv-rv20,2),
  "skew_5pct_back":{"otm_put_iv":ivp5,"otm_call_iv":ivc5,"put_minus_call_pp":sk5},
  "hist_earnings_moves":{"n":len(moves),"avg_abs_1d_pct":avg_earn_move,
                          "median_abs_1d_pct":med_earn_move,
                          "implied_vs_avg_ratio": round(implied_move_back/avg_earn_move,2) if avg_earn_move else None},
  "term_structure":term,
}
with open("experiments/tsmc_earnings_iv_20260708/tsmc_earnings_iv_results.json","w") as f:
    json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False,indent=2))
