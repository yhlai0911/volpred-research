"""
趨勢文 evidence package:
半導體巨頭修正期間的隱含波動率偏斜 (put-call skew) 與 IV-RV gap 分析

Data sources: yfinance (NVDA, SMH price history + options)
Sample period: 2024-01-01 to 2026-06-27
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import json
import warnings
warnings.filterwarnings('ignore')

FIG_DIR = "experiments/trending_2026_06_28_semis_skew/figures"

# ── 1. 拉 NVDA, SMH, VIX 價格數據（各自下載避免多 ticker format 問題）───
print("拉 NVDA, SMH, VIX 歷史價格...")

def download_close(ticker, start='2024-01-01', end='2026-06-28'):
    d = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    # yfinance 新版 multi-level columns，取 Close
    if isinstance(d.columns, pd.MultiIndex):
        col = [c for c in d.columns if c[0] == 'Close']
        series = d[col[0]].dropna()
    else:
        series = d['Close'].dropna()
    return series

nvda = download_close('NVDA')
smh  = download_close('SMH')
vix  = download_close('^VIX')

print(f"  NVDA: {len(nvda)} rows, last=${float(nvda.iloc[-1]):.2f} on {nvda.index[-1].date()}")
print(f"  SMH:  {len(smh)} rows, last=${float(smh.iloc[-1]):.2f}")
print(f"  VIX:  {len(vix)} rows, last={float(vix.iloc[-1]):.1f}")

# ── 2. 計算 RV30 (30日滾動已實現波動率，年化) ────────────────────────────
def rv30(prices, window=30):
    log_ret = np.log(prices / prices.shift(1)).dropna()
    return log_ret.rolling(window).std() * np.sqrt(252)

nvda_rv30 = rv30(nvda)
smh_rv30  = rv30(smh)

nvda_rv30_current = float(nvda_rv30.dropna().iloc[-1]) * 100
nvda_rv30_12m_avg = float(nvda_rv30.dropna().iloc[-252:].mean()) * 100
print(f"  NVDA RV30 (當前): {nvda_rv30_current:.1f}%, 12M 均值: {nvda_rv30_12m_avg:.1f}%")

# ── 3. 計算 NVDA 大跌 episodes（距滾動高點 >10%）────────────────────────
nvda_peak = nvda.cummax()
nvda_dd   = (nvda / nvda_peak - 1) * 100  # negative = below peak

# 找 episode 起點：當日 dd < -10%，且前一交易日 dd >= -10%（或為首日）
in_drop = nvda_dd < -10
episode_starts = in_drop & (~in_drop.shift(1, fill_value=False))
ep_dates = nvda_dd.index[episode_starts]
print(f"\n大跌 episodes (NVDA > 10% from peak): {len(ep_dates)} 個")

event_stats = []
for ep in ep_dates:
    # 找谷底：從 episode 起點往後 90 交易日內
    ep_pos = nvda_dd.index.get_loc(ep)
    end_pos = min(ep_pos + 90, len(nvda_dd))
    sub = nvda_dd.iloc[ep_pos:end_pos]
    trough_date = sub.idxmin()
    trough_dd   = float(sub.min())

    # pre-RV30: episode 前 30 交易日均值
    pre_idx = max(ep_pos - 30, 0)
    pre_rv = float(nvda_rv30.iloc[pre_idx:ep_pos].mean()) * 100

    # post-RV30: 谷底後 30 交易日均值
    t_pos = nvda_dd.index.get_loc(trough_date)
    post_end = min(t_pos + 30, len(nvda_rv30))
    post_rv = float(nvda_rv30.iloc[t_pos:post_end].mean()) * 100

    event_stats.append({
        'episode_start': ep.date().isoformat(),
        'trough_date':   trough_date.date().isoformat(),
        'max_drawdown_pct': round(trough_dd, 1),
        'pre_rv30_ann_pct':  round(pre_rv, 1),
        'post_rv30_ann_pct': round(post_rv, 1),
        'rv_increase_ppt': round(post_rv - pre_rv, 1),
    })
    print(f"  {ep.date()}: trough {trough_date.date()} dd={trough_dd:.1f}%, "
          f"pre-RV={pre_rv:.1f}% → post-RV={post_rv:.1f}%")

event_df = pd.DataFrame(event_stats)
if len(event_stats) > 1:
    med_pre  = float(event_df['pre_rv30_ann_pct'].median())
    med_post = float(event_df['post_rv30_ann_pct'].median())
    med_inc  = float(event_df['rv_increase_ppt'].median())
    print(f"\n  中位數: pre-RV={med_pre:.1f}%, post-RV={med_post:.1f}%, Δ={med_inc:+.1f}ppt")
else:
    med_pre = med_post = med_inc = None

# ── 4. 取 NVDA 選擇權 IV ─────────────────────────────────────────────────
print("\n取 NVDA 選擇權鏈...")
nvda_ticker = yf.Ticker('NVDA')
smh_ticker  = yf.Ticker('SMH')

def get_skew(ticker_obj, label):
    records = []
    try:
        exp_dates = ticker_obj.options[:4]
        spot_raw = ticker_obj.fast_info.get('lastPrice', None)
        if spot_raw is None:
            hist = ticker_obj.history(period='1d')
            spot = float(hist['Close'].iloc[-1])
        else:
            spot = float(spot_raw)
        print(f"  {label} spot: ${spot:.2f}")
        for exp in exp_dates[:3]:
            try:
                chain = ticker_obj.option_chain(exp)
                calls = chain.calls[['strike','impliedVolatility','openInterest']].copy()
                puts  = chain.puts [['strike','impliedVolatility','openInterest']].copy()
                calls = calls[calls['impliedVolatility'] > 0]
                puts  = puts [puts ['impliedVolatility'] > 0]

                atm_c = (calls['strike'] - spot).abs().idxmin()
                atm_p = (puts ['strike'] - spot).abs().idxmin()
                atm_call_iv = float(calls.loc[atm_c,'impliedVolatility'])
                atm_put_iv  = float(puts.loc[atm_p,'impliedVolatility'])

                # OTM proxy: puts ~0.92-0.97 spot, calls ~1.03-1.08 spot
                otm_puts  = puts[(puts['strike'] >= spot*0.90) & (puts['strike'] <= spot*0.97)]
                otm_calls = calls[(calls['strike'] >= spot*1.03) & (calls['strike'] <= spot*1.10)]

                if len(otm_puts) >= 2 and len(otm_calls) >= 2:
                    otm_put_iv  = float(otm_puts['impliedVolatility'].mean())
                    otm_call_iv = float(otm_calls['impliedVolatility'].mean())
                    skew_25d = otm_put_iv - otm_call_iv
                    skew_note = "OTM 0.90-0.97/1.03-1.10 proxy"
                else:
                    skew_25d = atm_put_iv - atm_call_iv
                    skew_note = "ATM put-call"

                records.append({
                    'ticker': label,
                    'expiry': exp,
                    'spot': round(spot, 2),
                    'atm_call_iv_pct': round(atm_call_iv * 100, 1),
                    'atm_put_iv_pct':  round(atm_put_iv * 100, 1),
                    'skew_25d_pct':    round(skew_25d * 100, 2),
                    'skew_note': skew_note,
                    'put_oi': int(puts['openInterest'].sum()),
                    'call_oi': int(calls['openInterest'].sum()),
                    'put_call_oi_ratio': round(float(puts['openInterest'].sum()) / max(float(calls['openInterest'].sum()), 1), 2),
                })
                print(f"    {exp}: ATM call={atm_call_iv*100:.1f}%, put={atm_put_iv*100:.1f}%, "
                      f"skew={skew_25d*100:+.2f}% ({skew_note})")
            except Exception as e:
                print(f"    {exp} 失敗: {e}")
    except Exception as e:
        print(f"  {label} options 失敗: {e}")
    return records

nvda_skew = get_skew(nvda_ticker, 'NVDA')
smh_skew  = get_skew(smh_ticker,  'SMH')

# ── 5. 圖 1: NVDA 股價 + RV30（雙 y 軸）─────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
fig.suptitle('NVDA 股價走勢與 30 日已實現波動率（2024–2026）', fontsize=13, fontweight='bold')

ax1, ax2 = axes
ax1.plot(nvda.index, nvda.values.astype(float), color='#1a73e8', linewidth=1.5, label='NVDA 收盤價 (USD)')
ax1.set_ylabel('股價 (USD)', fontsize=11)
ax1.legend(loc='upper left', fontsize=9)
ax1.grid(True, alpha=0.3)

# 標記大跌起始點
for ev in event_stats:
    ep_dt = pd.Timestamp(ev['episode_start'])
    ax1.axvline(ep_dt, color='#cc0000', alpha=0.5, linewidth=1.2, linestyle='--')

rv_vals = nvda_rv30.values.astype(float) * 100
ax2.fill_between(nvda_rv30.index, rv_vals, alpha=0.35, color='#e87313')
ax2.plot(nvda_rv30.index, rv_vals, color='#e87313', linewidth=1.2, label='NVDA 30日已實現波動率 (年化 %)')
ax2.set_ylabel('已實現波動率 (年化 %)', fontsize=11)
ax2.set_xlabel('日期', fontsize=11)
ax2.legend(loc='upper left', fontsize=9)
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.xticks(rotation=30)

# 標注說明
if event_stats:
    ax1.annotate('垂直虛線 = 大跌起始', xy=(0.02, 0.08), xycoords='axes fraction',
                fontsize=8, color='#cc0000', alpha=0.8)

plt.tight_layout()
fig1_path = f"{FIG_DIR}/nvda_price_rv30.png"
plt.savefig(fig1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"\n圖 1 存: {fig1_path}")

# ── 6. 圖 2: NVDA IV skew bar chart ─────────────────────────────────────
fig2_path = None
if nvda_skew:
    df_skew = pd.DataFrame(nvda_skew)
    fig2, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(df_skew))
    w = 0.32
    ax.bar(x - w/2, df_skew['atm_call_iv_pct'], w, label='ATM Call IV (%)', color='#1a73e8', alpha=0.82)
    ax.bar(x + w/2, df_skew['atm_put_iv_pct'],  w, label='ATM Put IV (%)',  color='#e84040', alpha=0.82)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r['expiry']}" for r in nvda_skew], fontsize=10)
    ax.set_ylabel('隱含波動率 (%)', fontsize=11)
    ax.set_title(f"NVDA 各到期日 ATM Call vs Put 隱含波動率（截至 {pd.Timestamp('today').date()}）", fontsize=11)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')
    for i, r in enumerate(nvda_skew):
        sv = r['skew_25d_pct']
        color = '#cc0000' if sv > 0 else '#008000'
        ymax = max(r['atm_call_iv_pct'], r['atm_put_iv_pct'])
        ax.text(i, ymax + 0.3, f"Skew\n{sv:+.1f}%", ha='center', fontsize=9,
                color=color, fontweight='bold')
    plt.tight_layout()
    fig2_path = f"{FIG_DIR}/nvda_iv_skew_bar.png"
    plt.savefig(fig2_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"圖 2 存: {fig2_path}")

# ── 7. 圖 3: NVDA RV30 vs 當前 ATM IV gap ───────────────────────────────
fig3_path = None
if nvda_skew:
    cur_iv_call = nvda_skew[0]['atm_call_iv_pct']
    cur_iv_put  = nvda_skew[0]['atm_put_iv_pct']
    rv_1y = nvda_rv30.iloc[-252:].copy()
    rv_1y_pct = rv_1y.values.astype(float) * 100

    fig3, ax = plt.subplots(figsize=(11, 5))
    ax.plot(rv_1y.index, rv_1y_pct, color='#1a73e8', linewidth=1.6, label='NVDA RV30 (年化 %)')
    ax.axhline(cur_iv_call, color='#e87313', linewidth=2, linestyle='--',
               label=f'ATM Call IV = {cur_iv_call:.1f}% (近月到期)')
    ax.axhline(cur_iv_put,  color='#e84040', linewidth=2, linestyle=':',
               label=f'ATM Put IV  = {cur_iv_put:.1f}% (近月到期)')
    ax.fill_between(rv_1y.index, rv_1y_pct, cur_iv_call,
                   where=(rv_1y_pct < cur_iv_call),
                   alpha=0.13, color='#e87313', label='IV > RV（選擇權相對貴）')
    ax.fill_between(rv_1y.index, rv_1y_pct, cur_iv_call,
                   where=(rv_1y_pct > cur_iv_call),
                   alpha=0.13, color='#1a73e8', label='RV > IV（選擇權相對便宜）')
    ax.set_ylabel('波動率 (年化 %)', fontsize=11)
    ax.set_xlabel('日期', fontsize=11)
    ax.set_title('NVDA：過去一年已實現波動率 vs 當前隱含波動率', fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=30)
    plt.tight_layout()
    fig3_path = f"{FIG_DIR}/nvda_iv_rv_gap.png"
    plt.savefig(fig3_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"圖 3 存: {fig3_path}")

# ── 8. Evidence JSON ──────────────────────────────────────────────────────
nvda_last = float(nvda.iloc[-1])
smh_last  = float(smh.iloc[-1])
vix_last  = float(vix.iloc[-1])
nvda_52h  = float(nvda.max())
smh_52h   = float(smh.max())
nvda_dd_now = (nvda_last / nvda_52h - 1) * 100
smh_dd_now  = (smh_last / smh_52h - 1) * 100

evidence = {
    "generated_at": pd.Timestamp.now().isoformat(),
    "sample_period": "2024-01-01 to 2026-06-27",
    "data_source": "yfinance",
    "key_numbers": {
        "NVDA_last": round(nvda_last, 2),
        "NVDA_52w_high": round(nvda_52h, 2),
        "NVDA_dd_from_high_pct": round(nvda_dd_now, 1),
        "SMH_last": round(smh_last, 2),
        "SMH_52w_high": round(smh_52h, 2),
        "SMH_dd_from_high_pct": round(smh_dd_now, 1),
        "VIX_last": round(vix_last, 1),
        "NVDA_RV30_current_pct": round(nvda_rv30_current, 1),
        "NVDA_RV30_12m_avg_pct": round(nvda_rv30_12m_avg, 1),
    },
    "median_event_stats": {
        "n_episodes": len(event_stats),
        "median_pre_rv30_pct": med_pre,
        "median_post_rv30_pct": med_post,
        "median_rv_increase_ppt": med_inc,
    },
    "nvda_options": nvda_skew,
    "smh_options": smh_skew,
    "event_episodes": event_stats,
    "figures": {
        "fig1": fig1_path,
        "fig2": fig2_path or "skipped",
        "fig3": fig3_path or "skipped",
    }
}

with open("experiments/trending_2026_06_28_semis_skew/evidence.json", "w", encoding="utf-8") as f:
    json.dump(evidence, f, ensure_ascii=False, indent=2)

print("\n=== EVIDENCE SUMMARY ===")
print(f"NVDA: ${nvda_last:.2f}, 距 52W 高點 {nvda_dd_now:.1f}%")
print(f"SMH:  ${smh_last:.2f}, 距 52W 高點 {smh_dd_now:.1f}%")
print(f"VIX:  {vix_last:.1f}")
print(f"NVDA RV30: {nvda_rv30_current:.1f}% (12M 均={nvda_rv30_12m_avg:.1f}%)")
if nvda_skew:
    r0 = nvda_skew[0]
    print(f"NVDA 近月 Call IV: {r0['atm_call_iv_pct']}%, Put IV: {r0['atm_put_iv_pct']}%, skew: {r0['skew_25d_pct']:+.2f}%")
print(f"大跌 episodes: {len(event_stats)} 個; 中位 pre-RV={med_pre}%, post-RV={med_post}%, Δ={med_inc}ppt")
print(f"圖: {fig1_path}, {fig2_path}, {fig3_path}")
print("========================")
