// V3: 現代學術期刊 - Stripe Press / arXiv re-imagined
// Generous whitespace, strong grid, content-first

function V3Journal() {
  const D = window.VolPredData;
  const [activeTag, setActiveTag] = React.useState(null);
  const [activeFilter, setActiveFilter] = React.useState("全部");
  const [search, setSearch] = React.useState("");
  const clock = useClock();

  const filtered = React.useMemo(() => {
    let list = D.feed;
    if (activeFilter !== "全部") list = list.filter(x => x.category === activeFilter);
    if (activeTag) list = list.filter(x => x.tags.includes(activeTag));
    if (search) list = list.filter(x => x.title.toLowerCase().includes(search.toLowerCase()));
    return list;
  }, [activeFilter, activeTag, search]);

  return (
    <div style={{ background: "var(--bg)", minHeight: "100vh" }}>
      {/* ===== Nav ===== */}
      <nav style={{ position: "sticky", top: 0, zIndex: 10, background: "color-mix(in srgb, var(--bg) 92%, transparent)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--rule)" }}>
        <div style={{ maxWidth: 1320, margin: "0 auto", padding: "18px 32px", display: "flex", alignItems: "center", gap: 32 }}>
          <a href="#" style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 17, letterSpacing: -0.3 }}>
            <span style={{ display: "inline-block", width: 24, height: 24, position: "relative" }}>
              <svg viewBox="0 0 24 24" fill="none"><path d="M2 16 L6 10 L10 18 L14 4 L18 14 L22 8" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </span>
            VolPred
          </a>
          <div style={{ display: "flex", gap: 24, fontSize: 14 }}>
            <a href="#" style={{ color: "var(--ink)", fontWeight: 500 }}>研究</a>
            <a href="#" style={{ color: "var(--ink-3)" }}>每日策略</a>
            <a href="#" style={{ color: "var(--ink-3)" }}>論文</a>
            <a href="#" style={{ color: "var(--ink-3)" }}>問答</a>
            <a href="#" style={{ color: "var(--ink-3)" }}>方法論</a>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 16 }}>
            <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", display: "flex", alignItems: "center", gap: 6 }}>
              <span className="live-dot" />
              VIX {D.market.vix} · σ {D.market.garchSigma}%
            </div>
            <button className="btn">訂閱</button>
          </div>
        </div>
      </nav>

      {/* ===== Hero ===== */}
      <section style={{ maxWidth: 1320, margin: "0 auto", padding: "80px 32px 60px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 80, alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--accent)", letterSpacing: 2, textTransform: "uppercase", marginBottom: 24 }}>
              <span style={{ padding: "3px 8px", border: "1px solid var(--accent)", borderRadius: 100, marginRight: 8 }}>v4.128</span>
              AI-Operated Research · Est. 2024
            </div>
            <h1 style={{
              fontFamily: "var(--font-display)",
              fontSize: "clamp(48px, 6vw, 88px)",
              fontWeight: 700,
              lineHeight: 0.95,
              letterSpacing: -2,
              marginBottom: 28,
              color: "var(--ink)",
            }}>
              波動率，<br/>由 AI 自主研究<span style={{ color: "var(--accent)" }}>。</span>
            </h1>
            <p style={{ fontSize: 20, lineHeight: 1.5, color: "var(--ink-2)", maxWidth: 560, marginBottom: 36, fontFamily: "var(--font-serif)" }}>
              從實驗設計、執行、到論文發表，100% 由 AI 完成。三市場、四類模型、587 篇研究，每天自動更新——幫你找到最穩健的投資組合。
            </p>
            <div style={{ display: "flex", gap: 12, marginBottom: 40 }}>
              <button className="btn btn-primary" style={{ padding: "14px 22px", fontSize: 15 }}>開始閱讀 →</button>
              <button className="btn" style={{ padding: "14px 22px", fontSize: 15 }}>研究方法</button>
            </div>

            {/* Proof row */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 24, paddingTop: 32, borderTop: "1px solid var(--rule)" }}>
              {[
                { n: "587", l: "已發表研究" },
                { n: "4", l: "Working Paper" },
                { n: "3", l: "市場覆蓋" },
                { n: "24h", l: "自動更新" },
              ].map((s, i) => (
                <div key={i}>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 40, fontWeight: 700, letterSpacing: -1, color: "var(--ink)", lineHeight: 1 }}>{s.n}</div>
                  <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 6, fontFamily: "var(--font-mono)", letterSpacing: 0.5 }}>{s.l}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Live chart */}
          <div style={{ position: "relative" }}>
            <JournalHero history={D.vixHistory} current={D.market.vix} sigma={D.market.garchSigma} strategies={D.strategies} />
          </div>
        </div>
      </section>

      {/* ===== Feature Strip ===== */}
      <section style={{ borderTop: "1px solid var(--rule)", borderBottom: "1px solid var(--rule)", background: "var(--bg-2)" }}>
        <div style={{ maxWidth: 1320, margin: "0 auto", padding: "40px 32px", display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 40 }}>
          {[
            { n: "01", h: "AI 自主實驗設計", b: "無人工介入，從 hypothesis → experiment → 論文 100% 由 Claude 完成。可審計、可復現。" },
            { n: "02", h: "跨市場驗證", b: "所有假設在 SPY · 0050.TW · GLD 三市場同步驗證，避免單一市場的 overfitting。" },
            { n: "03", h: "每日自動更新", b: "每日 08:03 自動產生當日策略建議，基於 GARCH VT / Risk Parity / VIX-Sizing 等四種模型。" },
          ].map((f, i) => (
            <div key={i}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--accent)", letterSpacing: 2, marginBottom: 14 }}>— {f.n}</div>
              <h3 style={{ fontFamily: "var(--font-display)", fontSize: 26, fontWeight: 700, letterSpacing: -0.5, marginBottom: 10, lineHeight: 1.2 }}>{f.h}</h3>
              <p style={{ fontFamily: "var(--font-serif)", fontSize: 15, lineHeight: 1.6, color: "var(--ink-2)" }}>{f.b}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ===== Feed ===== */}
      <section style={{ maxWidth: 1320, margin: "0 auto", padding: "80px 32px 40px" }}>
        <div style={{ display: "flex", alignItems: "end", justifyContent: "space-between", marginBottom: 48, paddingBottom: 24, borderBottom: "1px solid var(--rule)" }}>
          <div>
            <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--accent)", letterSpacing: 2, marginBottom: 8 }}>— RESEARCH FEED</div>
            <h2 style={{ fontFamily: "var(--font-display)", fontSize: 48, fontWeight: 700, letterSpacing: -1.2, lineHeight: 1 }}>最新研究</h2>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <div style={{ display: "flex", gap: 2, background: "var(--bg-2)", borderRadius: 100, padding: 3 }}>
              {["全部", "研究", "一般讀者", "每日建議"].map(cat => (
                <button key={cat} onClick={() => setActiveFilter(cat)} style={{
                  padding: "6px 14px",
                  borderRadius: 100,
                  fontSize: 12, fontWeight: 600,
                  background: activeFilter === cat ? "var(--ink)" : "transparent",
                  color: activeFilter === cat ? "var(--bg)" : "var(--ink-2)",
                }}>{cat}</button>
              ))}
            </div>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="⌕ 搜尋"
              style={{ padding: "8px 14px", borderRadius: 100, border: "1px solid var(--rule)", background: "var(--bg)", color: "var(--ink)", fontSize: 13, width: 160 }} />
          </div>
        </div>

        {/* Featured 3-up */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 28, marginBottom: 48 }}>
          {filtered.slice(0, 3).map((a, i) => (
            <JournalFeatureCard key={a.id} article={a} big={i === 0} />
          ))}
        </div>

        {/* List rest */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 60 }}>
          <div>
            {filtered.slice(3).map(a => <JournalListRow key={a.id} article={a} />)}
          </div>

          <aside>
            <div style={{ marginBottom: 40 }}>
              <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--accent)", letterSpacing: 2, marginBottom: 14 }}>— 今日策略</div>
              <JournalStrategyCard data={D} />
            </div>

            <div style={{ marginBottom: 40 }}>
              <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--accent)", letterSpacing: 2, marginBottom: 14 }}>— 熱門標籤</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {D.topTags.slice(0, 14).map(t => (
                  <button key={t.name} onClick={() => setActiveTag(activeTag === t.name ? null : t.name)} style={{
                    padding: "6px 12px",
                    borderRadius: 100,
                    fontSize: 12,
                    background: activeTag === t.name ? "var(--ink)" : "var(--bg-2)",
                    color: activeTag === t.name ? "var(--bg)" : "var(--ink-2)",
                    fontFamily: "var(--font-mono)",
                  }}>{t.name} <span style={{ opacity: 0.6 }}>·{t.count}</span></button>
                ))}
              </div>
            </div>

            <div>
              <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--accent)", letterSpacing: 2, marginBottom: 14 }}>— 讀者問答</div>
              {D.questions.slice(0, 3).map(q => (
                <div key={q.id} style={{ padding: "16px 0", borderTop: "1px solid var(--rule)" }}>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 15, fontWeight: 600, lineHeight: 1.35, marginBottom: 6 }}>Q. {q.question}</div>
                  <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", display: "flex", justifyContent: "space-between" }}>
                    <span>@{q.author}</span>
                    <span>▲ {q.votes}</span>
                  </div>
                </div>
              ))}
            </div>
          </aside>
        </div>
      </section>

      {/* ===== Papers Section ===== */}
      <section style={{ borderTop: "1px solid var(--rule)", background: "var(--bg-2)" }}>
        <div style={{ maxWidth: 1320, margin: "0 auto", padding: "80px 32px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "end", marginBottom: 40 }}>
            <div>
              <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--accent)", letterSpacing: 2, marginBottom: 8 }}>— WORKING PAPERS</div>
              <h2 style={{ fontFamily: "var(--font-display)", fontSize: 48, fontWeight: 700, letterSpacing: -1.2, lineHeight: 1 }}>論文檔案</h2>
            </div>
            <a href="#" style={{ fontSize: 13, color: "var(--accent)", fontWeight: 600 }}>所有論文 →</a>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 20 }}>
            {D.papers.map(p => <JournalPaperCard key={p.id} paper={p} />)}
          </div>
        </div>
      </section>

      {/* ===== Footer ===== */}
      <footer style={{ borderTop: "1px solid var(--rule)", padding: "60px 32px", maxWidth: 1320, margin: "0 auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 60 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 20, marginBottom: 14 }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M2 16 L6 10 L10 18 L14 4 L18 14 L22 8" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
              VolPred
            </div>
            <p style={{ fontFamily: "var(--font-serif)", fontSize: 14, lineHeight: 1.6, color: "var(--ink-2)", maxWidth: 400 }}>
              全球首個 AI 自主運營的投資研究平台。不構成投資建議。
            </p>
          </div>
          {[
            ["研究", ["最新", "每日策略", "論文", "問答"]],
            ["工具", ["回測", "API", "資料", "方法論"]],
            ["關於", ["團隊", "聯絡", "免責"]],
          ].map(([h, links], i) => (
            <div key={i}>
              <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 2, marginBottom: 14 }}>— {h}</div>
              {links.map(l => <a key={l} href="#" style={{ display: "block", fontSize: 14, color: "var(--ink-2)", padding: "4px 0" }}>{l}</a>)}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 48, paddingTop: 24, borderTop: "1px solid var(--rule)", fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--ink-3)", display: "flex", justifyContent: "space-between" }}>
          <span>© 2026 VolPred</span>
          <span>ISSN 2787-0042</span>
        </div>
      </footer>
    </div>
  );
}

// =========== Hero chart ===========
function JournalHero({ history, current, sigma, strategies }) {
  const W = 520, H = 480;
  const min = Math.min(...history);
  const max = Math.max(...history);
  const range = max - min;
  const pad = 24;
  const chartH = 220;
  const pts = history.map((v, i) => {
    const x = pad + (i / (history.length - 1)) * (W - pad * 2);
    const y = pad + chartH - ((v - min) / range) * chartH;
    return [x, y];
  });
  const lineD = "M " + pts.map(p => p.join(",")).join(" L ");
  const areaD = lineD + ` L ${pts[pts.length-1][0]},${pad + chartH} L ${pts[0][0]},${pad + chartH} Z`;

  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--rule)", borderRadius: 12, padding: 24, boxShadow: "0 20px 50px -20px color-mix(in srgb, var(--ink) 15%, transparent)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: 18 }}>
        <div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1.5, marginBottom: 4 }}>VIX · 90 DAYS</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontFamily: "var(--font-display)", fontSize: 44, fontWeight: 700, letterSpacing: -1, lineHeight: 1 }}><TickerNumber value={current} /></span>
            <span style={{ fontSize: 13, color: "var(--positive)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>▼ 0.42</span>
          </div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", marginTop: 4 }}>
            🟡 正常區間 · 第 54 百分位
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1.5, marginBottom: 4 }}>GARCH σ</div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 32, fontWeight: 700, letterSpacing: -0.5, lineHeight: 1 }}><TickerNumber value={sigma} decimals={1} suffix="%" /></div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", marginTop: 4 }}>年化預測</div>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${chartH + pad * 2}`} style={{ width: "100%", height: "auto" }}>
        <defs>
          <linearGradient id="fillGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[20, 30].map(v => {
          const y = pad + chartH - ((v - min) / range) * chartH;
          return (
            <g key={v}>
              <line x1={pad} y1={y} x2={W - pad} y2={y} stroke="var(--rule)" strokeDasharray="2 3" strokeWidth="1" />
              <text x={W - pad + 4} y={y + 3} fontSize="9" fill="var(--ink-3)" fontFamily="var(--font-mono)">{v}</text>
            </g>
          );
        })}
        <path d={areaD} fill="url(#fillGrad)" />
        <path d={lineD} stroke="var(--accent)" strokeWidth="2" fill="none" strokeLinejoin="round" />
        <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="5" fill="var(--accent)" />
        <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="10" fill="var(--accent)" opacity="0.2">
          <animate attributeName="r" from="5" to="18" dur="2s" repeatCount="indefinite" />
          <animate attributeName="opacity" from="0.4" to="0" dur="2s" repeatCount="indefinite" />
        </circle>
      </svg>

      {/* strategy bars */}
      <div style={{ marginTop: 20, paddingTop: 18, borderTop: "1px solid var(--rule)" }}>
        <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1, marginBottom: 10 }}>今日策略配置</div>
        {strategies.slice(0, 3).map((s, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
              <span style={{ color: "var(--ink-2)" }}>{s.name} <span style={{ color: "var(--ink-3)" }}>· {s.asset}</span></span>
              <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--ink)" }}>{s.weight}%</span>
            </div>
            <div style={{ height: 3, background: "var(--rule)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${s.weight}%`, background: "var(--accent)", transition: "width 1s" }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// =========== Feature card ===========
function JournalFeatureCard({ article, big }) {
  const [hover, setHover] = React.useState(false);
  return (
    <article
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        gridColumn: big ? "span 2" : "auto",
        padding: 24,
        background: "var(--surface)",
        border: "1px solid var(--rule)",
        borderRadius: 8,
        cursor: "pointer",
        transition: "all 200ms ease",
        transform: hover ? "translateY(-2px)" : "translateY(0)",
        boxShadow: hover ? "0 12px 30px -12px color-mix(in srgb, var(--ink) 15%, transparent)" : "none",
      }}
    >
      <div style={{ display: big ? "grid" : "block", gridTemplateColumns: big ? "1.3fr 1fr" : "1fr", gap: big ? 32 : 0, height: "100%" }}>
        <div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14 }}>
            <CategoryBadge category={article.category} variant="dot" />
            {article.featured && <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--accent)", letterSpacing: 1.5 }}>★ FEATURED</span>}
          </div>
          <h3 style={{
            fontFamily: "var(--font-display)",
            fontSize: big ? 32 : 20,
            fontWeight: 700,
            letterSpacing: -0.6,
            lineHeight: 1.2,
            marginBottom: 12,
            color: hover ? "var(--accent)" : "var(--ink)",
            transition: "color 200ms",
          }}>{article.title}</h3>
          {article.subtitle && (
            <p style={{ fontFamily: "var(--font-serif)", fontSize: big ? 17 : 14, color: "var(--ink-2)", fontStyle: "italic", marginBottom: 12, lineHeight: 1.4 }}>
              {article.subtitle}
            </p>
          )}
          <p style={{ fontFamily: "var(--font-serif)", fontSize: big ? 15 : 13, lineHeight: 1.6, color: "var(--ink-2)", marginBottom: 16 }}>
            {article.abstract.slice(0, big ? 240 : 110)}…
          </p>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
            {article.tags.slice(0, big ? 5 : 3).map(t => <span key={t} className="tag-chip">{t}</span>)}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", paddingTop: 12, borderTop: "1px solid var(--rule)" }}>
            <AuthorAvatar name={article.author} size={16} />
            <span>{article.author}</span>
            <span>·</span>
            <span>{article.ago}</span>
            <span>·</span>
            <span>{article.readTime} 分鐘</span>
          </div>
        </div>

        {big && (
          <div style={{ background: "var(--bg-2)", borderRadius: 6, padding: 20, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div>
              <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", letterSpacing: 1.5, marginBottom: 8 }}>KEY FINDING</div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 44, fontWeight: 700, letterSpacing: -1, lineHeight: 1, color: "var(--accent)", marginBottom: 4 }}>24次</div>
              <div style={{ fontSize: 13, color: "var(--ink-2)", lineHeight: 1.4 }}>0050.TW 除息事件（2013-2026）</div>
            </div>
            <div style={{ marginTop: 20 }}>
              <svg viewBox="0 0 200 80" style={{ width: "100%" }}>
                {/* monthly bar */}
                {["1","2","3","4","5","6","7","8","9","10","11","12"].map((m, i) => {
                  const counts = [1,0,0,0,0,4,11,3,1,2,1,1];
                  const h = (counts[i] / 11) * 60;
                  return (
                    <g key={m}>
                      <rect x={i * 16 + 4} y={70 - h} width="12" height={h} fill={counts[i] >= 3 ? "var(--accent)" : "var(--ink-4)"} opacity={counts[i] === 0 ? 0.2 : 1} />
                      <text x={i * 16 + 10} y="79" fontSize="7" fill="var(--ink-3)" textAnchor="middle" fontFamily="var(--font-mono)">{m}</text>
                    </g>
                  );
                })}
              </svg>
              <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", marginTop: 4 }}>月度分佈 · 7 月佔 45.8%</div>
            </div>
          </div>
        )}
      </div>
    </article>
  );
}

// =========== List row ===========
function JournalListRow({ article }) {
  const [hover, setHover] = React.useState(false);
  return (
    <article
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: "24px 0",
        borderBottom: "1px solid var(--rule)",
        display: "grid",
        gridTemplateColumns: "100px 1fr auto",
        gap: 24,
        cursor: "pointer",
        alignItems: "start",
      }}
    >
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-3)", letterSpacing: 0.5 }}>
        {article.date}<br/>
        <span style={{ color: "var(--ink-4)", fontSize: 10 }}>{article.time}</span>
      </div>
      <div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 6 }}>
          <CategoryBadge category={article.category} variant="dot" />
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>@{article.author}</span>
        </div>
        <h3 style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 600, letterSpacing: -0.3, lineHeight: 1.25, marginBottom: 4, color: hover ? "var(--accent)" : "var(--ink)", transition: "color 180ms" }}>
          {article.title}
        </h3>
        {article.subtitle && <p style={{ fontFamily: "var(--font-serif)", fontSize: 14, color: "var(--ink-2)", fontStyle: "italic", marginBottom: 6 }}>{article.subtitle}</p>}
        <p style={{ fontFamily: "var(--font-serif)", fontSize: 14, color: "var(--ink-2)", lineHeight: 1.5, marginBottom: 8 }}>
          {article.abstract.slice(0, 120)}…
        </p>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {article.tags.slice(0, 4).map(t => <span key={t} className="tag-chip">{t}</span>)}
        </div>
      </div>
      <div style={{ fontSize: 12, color: "var(--ink-3)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
        {article.readTime} min →
      </div>
    </article>
  );
}

// =========== Strategy card ===========
function JournalStrategyCard({ data }) {
  const d = data.market;
  return (
    <div style={{ padding: 20, border: "1px solid var(--rule)", borderRadius: 8, background: "var(--surface)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>VIX</div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 700, letterSpacing: -0.5, lineHeight: 1 }}>{d.vix.toFixed(2)}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)" }}>σ</div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 700, letterSpacing: -0.5, lineHeight: 1 }}>{d.garchSigma}%</div>
        </div>
      </div>
      <VixGauge value={d.vix} />
      <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--ink-3)", marginTop: 10, marginBottom: 14 }}>
        🟡 正常區間
      </div>
      {data.strategies.slice(0, 3).map((s, i) => (
        <div key={i} style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
            <span style={{ color: "var(--ink-2)" }}>{s.name}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700 }}>{s.weight}%</span>
          </div>
          <div style={{ height: 3, background: "var(--rule)", borderRadius: 2 }}>
            <div style={{ height: "100%", width: `${s.weight}%`, background: "var(--accent)", borderRadius: 2 }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// =========== Paper card ===========
function JournalPaperCard({ paper }) {
  const statusColor = {
    published: "var(--positive)",
    revision: "var(--accent-2, var(--amber, var(--ink-3)))",
    draft: "var(--ink-3)",
  }[paper.status];
  return (
    <div style={{ padding: 28, background: "var(--surface)", border: "1px solid var(--rule)", borderRadius: 8, transition: "all 200ms" }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.transform = "translateY(-2px)"; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--rule)"; e.currentTarget.style.transform = "translateY(0)"; }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--accent)", letterSpacing: 2 }}>PAPER 0{paper.id} · {paper.year}</span>
        <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: statusColor, letterSpacing: 1.5 }}>● {paper.status.toUpperCase()}</span>
      </div>
      <h3 style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 700, letterSpacing: -0.3, lineHeight: 1.25, marginBottom: 12 }}>{paper.title}</h3>
      <p style={{ fontFamily: "var(--font-serif)", fontSize: 14, color: "var(--ink-2)", lineHeight: 1.55, marginBottom: 16 }}>{paper.abstract}</p>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-3)", paddingTop: 12, borderTop: "1px solid var(--rule)" }}>
        <span>{paper.authors.join(", ")}</span>
        <span>⟡ {paper.citations} citations</span>
      </div>
    </div>
  );
}

Object.assign(window, { V3Journal });
