import React from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Bell,
  CheckCircle2,
  Clock,
  FileText,
  Gauge,
  Shield,
  Target,
  WalletCards,
} from "lucide-react";
import { radarData } from "./data";
import "./styles.css";

function Metric({ label, value, tone = "neutral" }) {
  return (
    <div className={`metric metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SectionTitle({ icon: Icon, title, action }) {
  return (
    <div className="section-title">
      <div>
        <Icon size={18} />
        <h2>{title}</h2>
      </div>
      {action ? <a href={action.href}>{action.label}</a> : null}
    </div>
  );
}

function App() {
  const data = radarData;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#">
          <span>VolPred</span>
          <strong>Radar</strong>
        </a>
        <nav>
          <a className="active" href="#today"><Gauge size={18} />今日戰情</a>
          <a href="#predictions"><Target size={18} />預測驗證</a>
          <a href="#strategy"><BarChart3 size={18} />策略配置</a>
          <a href="#membership"><WalletCards size={18} />會員方案</a>
        </nav>
        <div className="powered">
          <span>Powered by</span>
          <strong>VolPred Research</strong>
        </div>
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">市場風險雷達</p>
            <h1>今天市場該保守一點</h1>
          </div>
          <div className="top-actions">
            <button><Bell size={16} />訂閱提醒</button>
            <a href="https://volpred.zeabur.app/" target="_blank" rel="noreferrer">
              回研究站 <ArrowRight size={16} />
            </a>
          </div>
        </header>

        <section id="today" className="risk-board">
          <div className="risk-summary">
            <div className="risk-head">
              <div>
                <span className="status-dot" />
                <p>截至 {data.asOf}</p>
                <h2>{data.market.regime}</h2>
              </div>
              <div className="score-ring">
                <strong>{data.market.score}</strong>
                <span>/100</span>
              </div>
            </div>
            <p className="market-message">{data.market.message}</p>
            <div className="metrics-grid">
              <Metric label="台股" value={data.market.twStatus} tone="green" />
              <Metric label="美股" value={data.market.usStatus} />
              <Metric label="VIX" value={data.market.vix} tone="amber" />
              <Metric label="年化波動" value={data.market.annualVolatility} tone="red" />
            </div>
          </div>

          <div className="operator-note">
            <AlertTriangle size={20} />
            <h3>今天怎麼用</h3>
            <p>不追價、不開大槓桿。已有部位以風險上限檢查，不因單日反彈把現金一次打滿。</p>
            <button>看完整風險說明</button>
          </div>
        </section>

        <section id="predictions" className="content-band">
          <SectionTitle
            icon={Target}
            title="正在等待驗證的預測"
            action={{ href: "https://volpred.zeabur.app/indicators", label: "完整競技場" }}
          />
          <div className="prediction-grid">
            {data.predictions.map((item) => (
              <article className="prediction" key={item.name}>
                <div className="pill-row">
                  <span>{item.type}</span>
                  <span className="pending"><Clock size={13} />{item.status}</span>
                </div>
                <h3>{item.name}</h3>
                <p>{item.call}</p>
                <dl>
                  <div><dt>對象日</dt><dd>{item.targetDate}</dd></div>
                  <div><dt>驗證</dt><dd>{item.verifyAt}</dd></div>
                  <div><dt>樣本</dt><dd>{item.sample}</dd></div>
                </dl>
              </article>
            ))}
          </div>
        </section>

        <section id="strategy" className="content-band split">
          <div>
            <SectionTitle icon={Shield} title="策略配置建議" />
            <div className="strategy-list">
              {data.strategies.map((item) => (
                <article className="strategy" key={item.name}>
                  <div>
                    <span>{item.profile}</span>
                    <h3>{item.name}</h3>
                    <p>{item.allocation}</p>
                  </div>
                  <div className="strategy-stats">
                    <span>MDD {item.mdd}</span>
                    <span>Sharpe {item.sharpe}</span>
                  </div>
                  <p>{item.note}</p>
                </article>
              ))}
            </div>
          </div>

          <div>
            <SectionTitle icon={FileText} title="回到原始證據" />
            <div className="evidence-list">
              {data.evidence.map((item) => (
                <a className="evidence" href={item.href} target="_blank" rel="noreferrer" key={item.title}>
                  <span>{item.tag}</span>
                  <strong>{item.title}</strong>
                  <ArrowRight size={16} />
                </a>
              ))}
            </div>
          </div>
        </section>

        <section id="membership" className="content-band">
          <SectionTitle icon={WalletCards} title="副牌會員化第一版" />
          <div className="pricing-grid">
            {data.pricing.map((plan) => (
              <article className={`price-card ${plan.plan === "Radar Plus" ? "featured" : ""}`} key={plan.plan}>
                <h3>{plan.plan}</h3>
                <strong>{plan.price}</strong>
                <ul>
                  {plan.features.map((feature) => (
                    <li key={feature}><CheckCircle2 size={15} />{feature}</li>
                  ))}
                </ul>
                <button>{plan.plan === "Free" ? "開始使用" : "加入等候名單"}</button>
              </article>
            ))}
          </div>
        </section>

        <section className="architecture-note">
          <Activity size={18} />
          <p>
            架構原則：副牌只換前台與轉換漏斗，研究資料、預測紀錄、策略績效、會員問答仍由 VolPred 原本系統提供。
          </p>
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
