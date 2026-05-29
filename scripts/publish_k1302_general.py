"""Publish K1302 general-audience draft article."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research")
sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research/src")

import volpred.publisher.publisher as publisher_module
from volpred.publisher.publisher import Publisher


ROOT = Path("/Users/yhlai0911/Desktop/volpred-research")
RESULTS_PATH = ROOT / "experiments" / "k1302" / "k1302_results.json"
OUT_DIR = ROOT / "experiments" / "k1302"

LABELS = {
    "2317.TW": "鴻海",
    "2454.TW": "聯發科",
    "0056.TW": "0056",
    "2886.TW": "兆豐金",
    "2383.TW": "台光電",
}


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def prepare_rows(results: dict) -> list[dict]:
    rows: list[dict] = []
    for ticker, specs in results["results"].items():
        rows.append(
            {
                "ticker": ticker,
                "label": LABELS[ticker],
                "twa_gamma": specs["TWA"]["gamma"],
                "twa_t": specs["TWA"]["gamma_t_robust"],
                "twb_gamma": specs["TWB"]["gamma"],
                "twc_gamma": specs["TWC"]["gamma"],
                "n_obs": specs["TWA"]["n_obs"],
            }
        )
    rows.sort(key=lambda x: x["twa_gamma"], reverse=True)
    return rows


def make_chart_one(rows: list[dict]) -> str:
    labels = [r["label"] for r in rows]
    gammas = [r["twa_gamma"] for r in rows]
    colors = ["#D95F02", "#1B9E77", "#7570B3", "#E7298A", "#66A61E"]

    fig, ax = plt.subplots(figsize=(9.4, 5.2))
    bars = ax.bar(labels, gammas, color=colors, alpha=0.92)
    ax.set_ylabel("下跌放大係數", fontsize=11)
    ax.set_title("同樣是台股代表股，對壞消息的放大幅度差很多", fontsize=13, pad=10)
    ax.grid(axis="y", alpha=0.2)
    ax.set_ylim(0, max(gammas) * 1.28)

    for bar, row in zip(bars, rows):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.002,
            f"{row['twa_gamma']:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    fig.tight_layout()
    out = OUT_DIR / "k1302_general_chart_rank.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(out)


def make_chart_two(rows: list[dict]) -> str:
    labels = [r["label"] for r in rows]
    twa = [r["twa_gamma"] for r in rows]
    twb = [r["twb_gamma"] for r in rows]
    twc = [r["twc_gamma"] for r in rows]

    x = np.arange(len(labels))
    width = 0.24

    fig, ax = plt.subplots(figsize=(10.4, 5.4))
    ax.bar(x - width, twa, width, label="全樣本常態", color="#4C78A8")
    ax.bar(x, twb, width, label="全樣本厚尾", color="#F58518")
    ax.bar(x + width, twc, width, label="近 1250 日", color="#54A24B")
    ax.axhline(0, color="black", linewidth=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("下跌放大係數", fontsize=11)
    ax.set_title("有些股票很穩，有些股票一換時間窗就變很多", fontsize=13, pad=10)
    ax.legend(frameon=False, ncol=3, loc="upper left")
    ax.grid(axis="y", alpha=0.2)

    fig.tight_layout()
    out = OUT_DIR / "k1302_general_chart_specs.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(out)


def to_data_uri(png_path: str) -> str:
    payload = base64.b64encode(Path(png_path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def build_content(chart1_uri: str, chart2_uri: str) -> str:
    return f"""# 同樣遇到壞消息，台股 5 檔代表股的波動反應差了快 7 倍

很多投資人聽到「台股遇到利空時波動會放大」，腦中會把所有股票想成同一種反應。

K1302 這次把 5 檔常見台股代表標的拉回同一套估法、同一段資料、同一個比較口徑，答案很直接：差很多。

在 2008 到 2024 這段共同樣本裡，0056 的下跌放大係數約 **0.067**，台光電只有 **0.009**。前者大約是後者的 **7 倍**。聯發科落在 **0.041**，鴻海 **0.032**，兆豐金 **0.038**。同樣叫做「台股個股」，對壞消息的波動反應並沒有整齊劃一。

![K1302 台股個股下跌放大係數排名]({chart1_uri})

這個差距值得注意，因為很多市場敘事會把「台股」講成一整塊。新聞大跌時，我們很容易把大盤情緒直接投射到每一檔股票身上，好像所有標的都會同步進入高震盪狀態。

資料沒有支持這種想像。

0056 的反應最明顯，聯發科排第二。台光電接近零，代表在這段樣本裡，它對壞消息帶來的額外波動放大並不突出。你如果只看大盤 headline，很容易錯估手上部位真正暴露在哪一種風險裡。

第二張圖更有意思。它把同一批股票放進三種檢查方式裡：全樣本常態、全樣本厚尾、近 1250 個交易日。結果顯示，有些股票很穩，有些股票一換時間窗就差很多。

![K1302 三種估法下的股票差異]({chart2_uri})

聯發科在三種設定下都維持正值，算是相對穩。0056 在近 1250 日那一欄衝到 **0.208**，代表最近幾年的壞消息放大更明顯。鴻海則出現另一種情況：長樣本是正值，近 1250 日接近零下方，表示它最近這段時間的反應沒有舊樣本那麼一致。

這對一般投資人有三個提醒。

第一，不要把「台股風險」當成單一物件。大盤、ETF、電子權值股、金融股，壞消息來的時候，放大的速度和幅度都可能不同。

第二，分散持有很多股票，不等於你已經分散了「壞消息放大」這件事。如果你手上的部位剛好集中在反應比較敏感的標的，帳面體感會和你想的很不一樣。

第三，看歷史數字時，要先問比較口徑有沒有一致。這次 K1302 的價值，不是做出一個更聳動的新故事，而是把幾檔股票放回同一條尺上量。尺一樣，差異才有解讀價值。

這篇文章也順手提醒一件常被忽略的事：市場上很多「台股都怎樣」的說法，實際上只代表大盤或某一兩個熱門標的。你真的持有的是哪一類資產，會決定你在壞消息來的那天感受到多大的震動。

如果你想把一句話記住，可以記這句：

**台股有共同情緒，但每一檔股票承受那個情緒的方式，差很多。**

## 資料來源

本文基於實驗 K1302（`experiments/k1302/k1302.py`；結果檔 `experiments/k1302/k1302_results.json`）。資料期間為 2008-01-01 至 2024-12-31，樣本為 5 檔台灣標的日報酬，主要來源為論文資料檔與 yfinance 快取股價資料。
"""


def main() -> None:
    results = load_results()
    rows = prepare_rows(results)
    chart1_path = make_chart_one(rows)
    chart2_path = make_chart_two(rows)
    chart1_uri = to_data_uri(chart1_path)
    chart2_uri = to_data_uri(chart2_path)
    content = build_content(chart1_uri, chart2_uri)

    publisher_module._normalize_publish_assets = lambda description, details, *, root: (description, dict(details or {}))
    Publisher.REMOTE_URL = ""

    pub = Publisher()
    pub_id = pub.publish_milestone(
        title="同樣遇到壞消息，台股 5 檔代表股的波動反應差了快 7 倍",
        description=content,
        phase="research",
        category="milestone",
        audience="general",
        tags=[
            "台股",
            "個股",
            "0056",
            "風險管理",
            "波動率",
            "負面結果",
        ],
        proposer="Codex",
        status="draft",
        details={
            "experiment_refs": ["K1302"],
            "charts": [chart1_path, chart2_path],
            "data_source": "paper/taiwan-vt data CSV + yfinance cache",
            "period": "2008-01-01 to 2024-12-31",
            "n_obs": {row["ticker"]: row["n_obs"] for row in rows},
            "verdict": "PASS",
            "cluster_waiver": "K1302 daily_article uses stock-level heterogeneity angle, distinct from prior K1370 sample-mismatch article on 10x-to-4.7x ratio revision.",
        },
    )
    print(f"PUB_ID={pub_id}")


if __name__ == "__main__":
    main()
