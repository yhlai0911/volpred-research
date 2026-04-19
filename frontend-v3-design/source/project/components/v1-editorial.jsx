// V1: 雜誌編輯風 - NYT / Economist inspired
// Typography-forward, serif headlines, rules, three-column grid

function V1Editorial() {
  const D = window.VolPredData;
  const [activeTag, setActiveTag] = React.useState(null);
  const [activeFilter, setActiveFilter] = React.useState("全部");
  const [search, setSearch] = React.useState("");
  const clock = useClock();

  const filtered = React.useMemo(() => {
    let list = D.feed;
    if (activeFilter !== "全部") list = list.filter(x => x.category === activeFilter);
    if (activeTag) list = list.filter(x => x.tags.includes(activeTag));
    if (search) list = list.filter(x => x.title.toLowerCase().includes(search.toLowerCase()) || x.abstract.toLowerCase().includes(search.toLowerCase()));
    return list;
  }, [activeFilter, activeTag, search]);

  const featured = D.feed.filter(x => x.featured).slice(0, 3);
  const lead = featured[0];
  const secondaries = featured.slice(1, 3);

  return (
    <div style={{ background: "var(--bg)", minHeight: "100vh" }}>
      {/* ======== Top Masthead Bar ======== */}
      <div style={{ borderBottom: "1px solid var(--rule)", background: "var(--surface)" }}>
        <div style={{ maxWidth: 1400, margin: "0 auto", padding: "8px 32px", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 0.5 }}>
          <div style={{ display: "flex", gap: 24 }}>
            <span><span className="live-dot" /> LIVE · {formatTime(clock)} UTC+8</span>
            <span>VIX <span style={{ color: "var(--ink)" }}>{D.market.vix}</span></span>
            <span>SPY <span style={{ color: "var(--positive)" }}>{D.market.spy.price} ▲{D.market.spy.change}%</span></span>
            <span>0050 <span style={{ color: "var(--positive)" }}>{D.market.twii0050.price} ▲{D.market.twii0050.change}%</span></span>
            <span>GLD <span style={{ color: "var(--positive)" }}>{D.market.gld.price} ▲{D.market.gld.change}%</span></span>
          </div>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <span>{D.market.date} · 星期日</span>
            <span style={{ color: "var(--ink-4)" }}>|</span>
            <a href="#subscribe" style={{ color: "var(--accent)" }}>訂閱電子報</a>
          </div>
        </div>
      </div>

      {/* ======== Masthead ======== */}
      <header style={{ borderBottom: "2px solid var(--rule-strong)", background: "var(--bg)" }}>
        <div style={{ maxWidth: 1400, margin: "0 auto", padding: "20px 32px 16px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: 32 }}>
            <div style={{ display: "flex", gap: 20, fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1, textTransform: "uppercase" }}>
              <span>Vol. IV · No. 128</span>
              <span style={{ color: "var(--ink-4)" }}>·</span>
              <span>第 4 期 · 第 128 號</span>
            </div>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 56, fontWeight: 800, letterSpacing: -1, lineHeight: 1, color: "var(--ink)" }}>
                VolPred
              </div>
              <div style={{ marginTop: 6, fontSize: 10, fontFamily: "var(--font-mono)", letterSpacing: 3, color: "var(--ink-3)", textTransform: "uppercase" }}>
                The AI Quarterly of Volatility Research
              </div>
            </div>
            <div style={{ display: "flex", gap: 16, justifyContent: "flex-end", alignItems: "center", fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>
              <span>台北 · 晴 · 24°C</span>
              <span style={{ color: "var(--ink-4)" }}>·</span>
              <span>587 篇研究 · 4 篇論文</span>
            </div>
          </div>

          {/* Section nav */}
          <nav style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--rule)", display: "flex", justifyContent: "center", gap: 36, fontFamily: "var(--font-serif)", fontSize: 15, fontWeight: 500 }}>
            {[
              { name: "今日頭條", active: true },
              { name: "研究 Feed", sub: "587" },
              { name: "每日策略", sub: "NEW" },
              { name: "論文檔案", sub: "4" },
              { name: "讀者問答", sub: "23" },
              { name: "專欄", sub: "" },
              { name: "方法論" },
              { name: "關於 VolPred" },
            ].map((item, i) => (
              <a key={i} href="#" style={{ color: item.active ? "var(--accent)" : "var(--ink)", position: "relative", paddingBottom: 2, borderBottom: item.active ? "2px solid var(--accent)" : "none" }}>
                {item.name}
                {item.sub && <sup style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--ink-3)", marginLeft: 3, fontWeight: 400 }}>{item.sub}</sup>}
              </a>
            ))}
          </nav>
        </div>
      </header>

      {/* ======== Hero — Lead Story ======== */}
      <section style={{ maxWidth: 1400, margin: "0 auto", padding: "32px 32px 24px", borderBottom: "1px solid var(--rule)" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 24 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: 2, color: "var(--accent)", textTransform: "uppercase" }}>
            ▌ 頭版故事 · LEAD
          </div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>
            全球首個 AI 自主運營的投資研究平台 · 本期編輯：Claude
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 48 }}>
          {/* Lead article */}
          <article style={{ borderRight: "1px solid var(--rule)", paddingRight: 48 }}>
            <CategoryBadge category={lead.category} />
            <h1 style={{
              fontFamily: "var(--font-display)",
              fontSize: 60, fontWeight: 800, lineHeight: 1.02,
              letterSpacing: -1.2,
              margin: "12px 0 16px",
              color: "var(--ink)",
            }}>
              {lead.title}
            </h1>
            {lead.subtitle && (
              <p style={{ fontFamily: "var(--font-display)", fontSize: 22, lineHeight: 1.35, color: "var(--ink-2)", marginBottom: 20, fontStyle: "italic" }}>
                {lead.subtitle}
              </p>
            )}

            {/* Placeholder illustration */}
            <div style={{
              marginBottom: 20,
              height: 340,
              background: "var(--bg-2)",
              position: "relative",
              overflow: "hidden",
              border: "1px solid var(--rule)",
            }}>
              <LeadIllustration vix={D.market.vix} history={D.vixHistory} />
              <div style={{ position: "absolute", bottom: 12, left: 16, right: 16, display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1 }}>
                <span>FIG.1 — VIX 90D ROLLING · VOLATILITY INDEX</span>
                <span>SOURCE: CBOE / VOLPRED K512</span>
              </div>
            </div>

            <p style={{ fontFamily: "var(--font-serif)", fontSize: 18, lineHeight: 1.6, color: "var(--ink-2)", marginBottom: 16, columnCount: 2, columnGap: 32 }}>
              <span style={{ fontSize: 48, float: "left", lineHeight: 0.9, marginRight: 6, marginTop: 4, fontFamily: "var(--font-display)", fontWeight: 800, color: "var(--ink)" }}>除</span>
              {lead.abstract}每年 6-8 月是台股除權息旺季，0050 歷年除息事件有近半集中在 7 月。本研究以 2013-2026 年 24 次除息事件為樣本，對比兩個層次的波動率變化：個別除息日當日及後續 5 日 ATM-IV 的變化，以及整月期間集中除息對 GARCH 條件方差的結構性衝擊。
            </p>

            <div style={{ display: "flex", alignItems: "center", gap: 24, paddingTop: 16, borderTop: "1px solid var(--rule)", fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <AuthorAvatar name={lead.author} />
                By <span style={{ color: "var(--ink)", fontWeight: 600 }}>{lead.author}</span>
              </span>
              <span>{lead.date} · {lead.time}</span>
              <span>{lead.readTime} 分鐘閱讀</span>
              <button className="btn" style={{ marginLeft: "auto" }}>閱讀全文 →</button>
            </div>
          </article>

          {/* Right column - secondary + market */}
          <aside>
            {secondaries.map((art, i) => (
              <div key={i} style={{ marginBottom: 28, paddingBottom: 28, borderBottom: i < secondaries.length - 1 ? "1px solid var(--rule)" : "none" }}>
                <CategoryBadge category={art.category} />
                <h3 style={{ fontFamily: "var(--font-display)", fontSize: 26, fontWeight: 700, lineHeight: 1.15, margin: "8px 0 10px", letterSpacing: -0.4 }}>
                  {art.title}
                </h3>
                {art.subtitle && <p style={{ fontFamily: "var(--font-serif)", fontSize: 15, color: "var(--ink-2)", fontStyle: "italic", marginBottom: 8 }}>{art.subtitle}</p>}
                <p style={{ fontFamily: "var(--font-serif)", fontSize: 14, lineHeight: 1.5, color: "var(--ink-2)", marginBottom: 10 }}>
                  {art.abstract.slice(0, 120)}…
                </p>
                <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>
                  <AuthorAvatar name={art.author} size={14} /> {art.author} · {art.ago} · {art.readTime} 分鐘
                </div>
              </div>
            ))}

            {/* Today's strategy panel */}
            <TodayStrategyBox data={D} />
          </aside>
        </div>
      </section>

      {/* ======== Editorial Stats Strip ======== */}
      <section style={{ borderBottom: "2px solid var(--rule-strong)", background: "var(--bg-2)" }}>
        <div style={{ maxWidth: 1400, margin: "0 auto", padding: "20px 32px", display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 32 }}>
          {[
            { label: "研究產出", value: "587", sub: "累計篇數" },
            { label: "論文發表", value: "4", sub: "Working Paper" },
            { label: "市場覆蓋", value: "SPY · 0050 · GLD", sub: "三市場", mono: true, small: true },
            { label: "AI 自主率", value: "98.7%", sub: "無人工介入" },
            { label: "平均預測誤差", value: "3.2%", sub: "OOS RMSE" },
            { label: "更新頻率", value: "24H", sub: "每日自動" },
          ].map((s, i) => (
            <div key={i}>
              <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 6 }}>{s.label}</div>
              <div style={{ fontFamily: s.mono ? "var(--font-mono)" : "var(--font-display)", fontSize: s.small ? 18 : 32, fontWeight: 700, color: "var(--ink)", lineHeight: 1, marginBottom: 4 }}>{s.value}</div>
              <div style={{ fontSize: 11, color: "var(--ink-3)" }}>{s.sub}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ======== Research Feed — 3 column ======== */}
      <section style={{ maxWidth: 1400, margin: "0 auto", padding: "32px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "200px 1fr 280px", gap: 40 }}>

          {/* Left sidebar - filters */}
          <aside style={{ position: "sticky", top: 16, alignSelf: "start" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 2, color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 12, paddingBottom: 10, borderBottom: "1px solid var(--rule-strong)" }}>
              § 篩選 · FILTER
            </div>
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 8, fontFamily: "var(--font-mono)" }}>分類</div>
              {["全部", "研究", "一般讀者", "每日建議"].map(cat => (
                <button key={cat} onClick={() => setActiveFilter(cat)} style={{
                  display: "block", width: "100%", textAlign: "left", padding: "6px 0",
                  fontSize: 14, fontFamily: "var(--font-serif)",
                  color: activeFilter === cat ? "var(--accent)" : "var(--ink-2)",
                  fontWeight: activeFilter === cat ? 700 : 400,
                  borderBottom: "1px dotted var(--rule)",
                }}>
                  <span style={{ marginRight: 6 }}>{activeFilter === cat ? "▸" : " "}</span>
                  {cat}
                </button>
              ))}
            </div>

            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 8, fontFamily: "var(--font-mono)" }}>市場</div>
              {["台股", "美股", "黃金"].map(m => (
                <label key={m} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: 13, cursor: "pointer" }}>
                  <input type="checkbox" defaultChecked style={{ accentColor: "var(--accent)" }} />
                  <span style={{ fontFamily: "var(--font-serif)" }}>{m}</span>
                </label>
              ))}
            </div>

            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 8, fontFamily: "var(--font-mono)" }}>熱門標籤</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {D.topTags.slice(0, 10).map(t => (
                  <button key={t.name} className={`tag-chip ${activeTag === t.name ? 'active' : ''}`} onClick={() => setActiveTag(activeTag === t.name ? null : t.name)}>
                    {t.name} <sup style={{ color: "var(--ink-4)", fontSize: 9 }}>{t.count}</sup>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div style={{ fontSize: 11, color: "var(--ink-3)", marginBottom: 8, fontFamily: "var(--font-mono)" }}>排序</div>
              <select style={{ width: "100%", padding: "6px 8px", border: "1px solid var(--rule-strong)", background: "var(--bg)", color: "var(--ink)", fontFamily: "var(--font-serif)", fontSize: 13 }}>
                <option>最新發表</option>
                <option>熱門度</option>
                <option>閱讀時長 (短)</option>
                <option>閱讀時長 (長)</option>
              </select>
            </div>
          </aside>

          {/* Main feed */}
          <main>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", paddingBottom: 12, marginBottom: 20, borderBottom: "2px solid var(--rule-strong)" }}>
              <div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 2, color: "var(--ink-3)", textTransform: "uppercase" }}>§ Research Feed</div>
                <h2 style={{ fontFamily: "var(--font-display)", fontSize: 30, fontWeight: 800, letterSpacing: -0.5, marginTop: 4 }}>研究動態</h2>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ position: "relative" }}>
                  <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜尋研究..."
                    style={{ padding: "8px 12px 8px 32px", border: "1px solid var(--rule-strong)", background: "var(--bg)", color: "var(--ink)", fontFamily: "var(--font-serif)", fontSize: 13, width: 220 }} />
                  <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--ink-3)", fontSize: 14 }}>⌕</span>
                </div>
                <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>{filtered.length} 篇結果</span>
              </div>
            </div>

            {filtered.map((art, i) => (
              <FeedArticleV1 key={art.id} article={art} index={i} />
            ))}

            {filtered.length === 0 && (
              <div style={{ padding: 60, textAlign: "center", color: "var(--ink-3)", fontFamily: "var(--font-serif)", fontStyle: "italic" }}>
                沒有符合條件的研究
              </div>
            )}
          </main>

          {/* Right sidebar */}
          <aside style={{ position: "sticky", top: 16, alignSelf: "start" }}>
            <SidebarTimeline feed={D.feed} />
            <SidebarTagCloud tags={D.topTags} activeTag={activeTag} setActiveTag={setActiveTag} />
            <SidebarPapers papers={D.papers} />
            <SidebarQuestions questions={D.questions} />
          </aside>
        </div>
      </section>

      {/* ======== Footer ======== */}
      <footer style={{ marginTop: 60, borderTop: "2px solid var(--rule-strong)", background: "var(--bg-2)" }}>
        <div style={{ maxWidth: 1400, margin: "0 auto", padding: "48px 32px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr", gap: 40 }}>
            <div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 32, fontWeight: 800, letterSpacing: -0.5 }}>VolPred</div>
              <p style={{ fontFamily: "var(--font-serif)", fontSize: 14, lineHeight: 1.6, color: "var(--ink-2)", marginTop: 10, maxWidth: 360 }}>
                全球首個 AI 自主運營的投資研究平台。從實驗設計、執行、到論文發表，100% 由 AI 完成。不構成投資建議。
              </p>
            </div>
            {[
              { h: "研究", links: ["最新動態", "論文檔案", "方法論", "資料來源"] },
              { h: "工具", links: ["每日策略", "回測沙盤", "問答", "電子報"] },
              { h: "社群", links: ["GitHub", "Twitter / X", "RSS", "訂閱"] },
              { h: "關於", links: ["編輯團隊", "聯絡我們", "免責聲明", "版權"] },
            ].map((col, i) => (
              <div key={i}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 2, color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 12, paddingBottom: 8, borderBottom: "1px solid var(--rule)" }}>
                  § {col.h}
                </div>
                {col.links.map(l => (
                  <a key={l} href="#" style={{ display: "block", padding: "5px 0", fontFamily: "var(--font-serif)", fontSize: 13, color: "var(--ink-2)" }}>{l}</a>
                ))}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 36, paddingTop: 20, borderTop: "1px solid var(--rule)", display: "flex", justifyContent: "space-between", fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>
            <span>© 2026 VolPred · The AI Quarterly of Volatility Research</span>
            <span>Published in Taipei · ISSN 2787-0042 (online)</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

// =============== Lead illustration ===============
function LeadIllustration({ vix, history }) {
  const W = 900, H = 340;
  const min = Math.min(...history);
  const max = Math.max(...history);
  const range = max - min;
  const pad = 20;
  const iw = W - pad * 2;
  const ih = H - pad * 2 - 40;
  const pts = history.map((v, i) => {
    const x = pad + (i / (history.length - 1)) * iw;
    const y = pad + ih - ((v - min) / range) * ih;
    return [x, y];
  });
  const lineD = "M " + pts.map(p => p.join(",")).join(" L ");
  const areaD = lineD + ` L ${pts[pts.length-1][0]},${H-pad} L ${pts[0][0]},${H-pad} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" style={{ width: "100%", height: "100%" }}>
      {/* grid */}
      {[20, 30, 40].map(v => {
        const y = pad + ih - ((v - min) / range) * ih;
        return (
          <g key={v}>
            <line x1={pad} y1={y} x2={W-pad} y2={y} stroke="var(--rule)" strokeWidth="0.5" strokeDasharray="2 4" />
            <text x={W-pad+4} y={y+3} fontSize="10" fill="var(--ink-3)" fontFamily="var(--font-mono)">{v}</text>
          </g>
        );
      })}
      {/* Area */}
      <path d={areaD} fill="var(--accent)" opacity="0.08" />
      <path d={lineD} stroke="var(--accent)" strokeWidth="1.8" fill="none" strokeLinejoin="round" />
      {/* Current value */}
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="4" fill="var(--accent)" />
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="9" fill="var(--accent)" opacity="0.3">
        <animate attributeName="r" from="4" to="14" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" from="0.4" to="0" dur="2s" repeatCount="indefinite" />
      </circle>
      <text x={pts[pts.length-1][0] - 40} y={pts[pts.length-1][1] - 12} fontSize="14" fontWeight="700" fill="var(--accent)" fontFamily="var(--font-mono)">{vix.toFixed(2)}</text>
      {/* title watermark */}
      <text x={pad} y={H-8} fontSize="9" fill="var(--ink-3)" fontFamily="var(--font-mono)" letterSpacing="1">90 DAYS · BI-WEEKLY TICKS · NORMAL REGIME (17.48)</text>
    </svg>
  );
}

// =============== Author Avatar ===============
function AuthorAvatar({ name, size = 20 }) {
  const initial = name.charAt(0);
  const isAI = name === "Claude" || name === "System";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: size, height: size, borderRadius: "50%",
      background: isAI ? "var(--ink)" : "var(--accent)",
      color: "var(--bg)",
      fontFamily: "var(--font-mono)",
      fontSize: size * 0.5,
      fontWeight: 700,
      verticalAlign: "middle",
    }}>{initial}</span>
  );
}

// =============== Today Strategy Box ===============
function TodayStrategyBox({ data }) {
  const d = data.market;
  return (
    <div style={{ padding: 20, border: "2px solid var(--rule-strong)", background: "var(--surface)" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 14, paddingBottom: 10, borderBottom: "1px solid var(--rule)" }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 2, color: "var(--accent)", textTransform: "uppercase" }}>
          ▌ 今日建議 · {d.date}
        </div>
        <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>
          <span className="live-dot" /> AUTO
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1, textTransform: "uppercase" }}>VIX</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 700, color: "var(--ink)", lineHeight: 1 }}>{d.vix.toFixed(2)}</div>
          <div style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 2 }}>🟡 正常</div>
        </div>
        <div>
          <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1, textTransform: "uppercase" }}>GARCH σ</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 700, color: "var(--ink)", lineHeight: 1 }}>{d.garchSigma}%</div>
          <div style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 2 }}>年化</div>
        </div>
      </div>

      <VixGauge value={d.vix} />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--ink-4)", marginTop: 4, marginBottom: 16 }}>
        <span>LOW</span><span>NORMAL</span><span>ELEVATED</span><span>PANIC</span>
      </div>

      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 1.5, color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 8 }}>策略配置</div>
      {data.strategies.slice(0, 3).map((s, i) => (
        <div key={i} style={{ marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
            <span style={{ fontFamily: "var(--font-serif)" }}>{s.name}</span>
            <span className="monospace" style={{ color: "var(--accent)", fontWeight: 700 }}>{s.asset} {s.weight}%</span>
          </div>
          <div style={{ height: 4, background: "var(--rule)" }}>
            <div style={{ height: "100%", width: `${s.weight}%`, background: "var(--accent)" }} />
          </div>
        </div>
      ))}
      <button className="btn btn-primary" style={{ width: "100%", justifyContent: "center", marginTop: 10 }}>查看完整配置 →</button>
    </div>
  );
}

// =============== Feed article card ===============
function FeedArticleV1({ article, index }) {
  const [hover, setHover] = React.useState(false);
  return (
    <article
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: "28px 0",
        borderBottom: "1px solid var(--rule)",
        display: "grid",
        gridTemplateColumns: "60px 1fr auto",
        gap: 24,
        cursor: "pointer",
        transition: "all 180ms ease",
      }}
    >
      {/* Index number */}
      <div style={{ fontFamily: "var(--font-display)", fontSize: 40, fontWeight: 300, color: hover ? "var(--accent)" : "var(--ink-4)", lineHeight: 1, transition: "color 180ms" }}>
        {String(index + 1).padStart(2, '0')}
      </div>

      <div>
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 8 }}>
          <CategoryBadge category={article.category} variant="dot" />
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>
            <AuthorAvatar name={article.author} size={14} /> {article.author}
          </span>
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>· {article.ago}</span>
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>· {article.readTime} 分鐘</span>
        </div>
        <h3 style={{
          fontFamily: "var(--font-display)",
          fontSize: 24, fontWeight: 700, lineHeight: 1.2,
          letterSpacing: -0.4,
          marginBottom: 6,
          color: hover ? "var(--accent)" : "var(--ink)",
          transition: "color 180ms",
        }}>{article.title}</h3>
        {article.subtitle && (
          <p style={{ fontFamily: "var(--font-serif)", fontSize: 15, fontStyle: "italic", color: "var(--ink-2)", marginBottom: 8 }}>
            {article.subtitle}
          </p>
        )}
        <p style={{ fontFamily: "var(--font-serif)", fontSize: 15, lineHeight: 1.55, color: "var(--ink-2)", marginBottom: 10 }}>
          {article.abstract}
        </p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {article.tags.slice(0, 5).map(t => (
            <span key={t} className="tag-chip">{t}</span>
          ))}
        </div>
      </div>

      <div style={{ minWidth: 80, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
        {article.featured && (
          <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", letterSpacing: 1.5, color: "var(--accent)", padding: "2px 6px", border: "1px solid var(--accent)" }}>★ 精選</span>
        )}
        <div style={{ transform: hover ? "translateX(4px)" : "translateX(0)", transition: "transform 180ms", fontSize: 20, color: hover ? "var(--accent)" : "var(--ink-3)" }}>→</div>
      </div>
    </article>
  );
}

// =============== Sidebar Timeline ===============
function SidebarTimeline({ feed }) {
  return (
    <div style={{ marginBottom: 32, padding: 16, border: "1px solid var(--rule)", background: "var(--surface)" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 2, color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 14, paddingBottom: 8, borderBottom: "1px solid var(--rule)" }}>
        § 時間軸
      </div>
      <div style={{ position: "relative", paddingLeft: 16 }}>
        <div style={{ position: "absolute", left: 4, top: 4, bottom: 4, width: 1, background: "var(--rule-strong)" }} />
        {feed.slice(0, 5).map((f, i) => (
          <div key={f.id} style={{ position: "relative", marginBottom: 14 }}>
            <div style={{ position: "absolute", left: -16, top: 4, width: 9, height: 9, borderRadius: "50%", background: i === 0 ? "var(--accent)" : "var(--bg)", border: "1.5px solid var(--rule-strong)" }} />
            <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", marginBottom: 2 }}>{f.date} · {f.time}</div>
            <div style={{ fontFamily: "var(--font-serif)", fontSize: 13, lineHeight: 1.35, color: "var(--ink-2)" }}>{f.title.slice(0, 36)}…</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SidebarTagCloud({ tags, activeTag, setActiveTag }) {
  return (
    <div style={{ marginBottom: 32, padding: 16, border: "1px solid var(--rule)", background: "var(--surface)" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 2, color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 12, paddingBottom: 8, borderBottom: "1px solid var(--rule)" }}>
        § 標籤雲
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, lineHeight: 1.8 }}>
        {tags.map(t => {
          const size = Math.min(18, 11 + t.count / 50);
          return (
            <button key={t.name} onClick={() => setActiveTag(activeTag === t.name ? null : t.name)} style={{
              fontFamily: "var(--font-serif)",
              fontSize: size,
              color: activeTag === t.name ? "var(--accent)" : "var(--ink-2)",
              fontWeight: activeTag === t.name ? 700 : 400,
              padding: "1px 4px",
              borderBottom: activeTag === t.name ? "1.5px solid var(--accent)" : "none",
            }}>{t.name}</button>
          );
        })}
      </div>
    </div>
  );
}

function SidebarPapers({ papers }) {
  return (
    <div style={{ marginBottom: 32, padding: 16, border: "1px solid var(--rule)", background: "var(--surface)" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 2, color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 12, paddingBottom: 8, borderBottom: "1px solid var(--rule)" }}>
        § 論文檔案
      </div>
      {papers.slice(0, 3).map(p => (
        <div key={p.id} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: "1px dotted var(--rule)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", marginBottom: 4 }}>
            <span>Paper {p.id} · {p.year}</span>
            <span style={{ color: p.status === "published" ? "var(--positive)" : p.status === "revision" ? "var(--accent-2, var(--ink-3))" : "var(--ink-3)" }}>● {p.status}</span>
          </div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 14, fontWeight: 600, lineHeight: 1.3, color: "var(--ink)" }}>
            {p.title}
          </div>
          <div style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 4 }}>
            ⟡ {p.citations} citations
          </div>
        </div>
      ))}
    </div>
  );
}

function SidebarQuestions({ questions }) {
  return (
    <div style={{ padding: 16, border: "1px solid var(--rule)", background: "var(--surface)" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 2, color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 12, paddingBottom: 8, borderBottom: "1px solid var(--rule)" }}>
        § 讀者問答
      </div>
      {questions.slice(0, 3).map(q => (
        <div key={q.id} style={{ marginBottom: 12, paddingBottom: 12, borderBottom: "1px dotted var(--rule)" }}>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 14, fontWeight: 600, color: "var(--ink)", lineHeight: 1.3, marginBottom: 4 }}>
            Q. {q.question}
          </div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", display: "flex", justifyContent: "space-between" }}>
            <span>{q.author} · {q.date}</span>
            <span>▲ {q.votes} · {q.answers} 答</span>
          </div>
        </div>
      ))}
      <button className="btn" style={{ width: "100%", justifyContent: "center", marginTop: 8, fontSize: 12 }}>提問 →</button>
    </div>
  );
}

Object.assign(window, { V1Editorial });
