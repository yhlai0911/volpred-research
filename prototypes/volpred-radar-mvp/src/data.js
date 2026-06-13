export const radarData = {
  asOf: "2026-06-13 09:10",
  market: {
    regime: "正常偏警戒",
    score: 63,
    twStatus: "盤中",
    usStatus: "今日已收盤",
    vix: 17.68,
    annualVolatility: "19.3%",
    message:
      "風險沒有到紅燈，但短端避險情緒升溫。今天不適合追價，策略部位維持防守比例。",
  },
  predictions: [
    {
      type: "猜漲跌",
      name: "美股→台股隔夜領先訊號",
      call: "昨晚美股收漲，預測今天 0050 跟著漲",
      targetDate: "2026-06-15",
      verifyAt: "2026-06-15 13:30",
      sample: "1/20",
      status: "等待驗證",
    },
    {
      type: "估風險範圍",
      name: "A4f-VIX9D-t 明日 SPY 2.5% VaR",
      call: "SPY 明日罕見大跌線：-1.8%",
      targetDate: "2026-06-15",
      verifyAt: "2026-06-16 04:00",
      sample: "2/20",
      status: "等待驗證",
    },
    {
      type: "猜漲跌",
      name: "VIX 危機預警（台股風險燈號）",
      call: "風險燈正常，未偵測到危機訊號",
      targetDate: "2026-06-15",
      verifyAt: "2026-06-15 13:30",
      sample: "1/20",
      status: "等待驗證",
    },
  ],
  strategies: [
    {
      name: "保守型 VT（Piecewise）",
      profile: "保守",
      allocation: "14% GLD / 14% SPY / 72% 現金",
      mdd: "-3.6%",
      sharpe: "2.82",
      note: "退休族與低回撤需求優先。VIX 12-20 時按公式逐步減碼。",
    },
    {
      name: "自適應三階 VT",
      profile: "平衡",
      allocation: "34% GLD / 34% SPY / 32% 現金",
      mdd: "-7.1%",
      sharpe: "2.65",
      note: "需要每天看 VIX，平靜時可加碼，緊張時退回現金。",
    },
    {
      name: "台股混合槓桿",
      profile: "積極",
      allocation: "49% 0050 / 51% 現金",
      mdd: "-10.3%",
      sharpe: "2.60",
      note: "需信用交易帳戶。適合能接受台股波動與紀律調倉的人。",
    },
  ],
  evidence: [
    {
      title: "好策略被成本吃掉 27%：11 個 VT 策略的實施費用拆解",
      tag: "成本檢查",
      href: "https://volpred.zeabur.app/reports/mile_f596a67c",
    },
    {
      title: "波動率模型是不是加越多料越好？SPY 這次給的答案是：先學會刪",
      tag: "模型驗證",
      href: "https://volpred.zeabur.app/reports/mile_5e0786d0",
    },
    {
      title: "市場一緊張就換另一套模型，真的會更安全嗎？",
      tag: "策略壓力測試",
      href: "https://volpred.zeabur.app/reports/mile_42b4330c",
    },
  ],
  pricing: [
    {
      plan: "Free",
      price: "$0",
      features: ["今日風險燈號", "公開預測戰績", "最新研究摘要"],
    },
    {
      plan: "Radar Plus",
      price: "NT$299/月",
      features: ["完整預測紀錄", "策略追蹤", "每日風險通知", "收藏研究"],
    },
    {
      plan: "Research Pro",
      price: "NT$599/月",
      features: ["會員提問", "完整實驗證據卡", "報告匯出", "進階策略檢查"],
    },
  ],
};
