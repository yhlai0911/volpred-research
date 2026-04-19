// V2: 金融終端機風 - Bloomberg Terminal / Tradingview inspired
// Dark-first, dense data, monospace everywhere

function V2Terminal() {
  const D = window.VolPredData;
  const [activeTag, setActiveTag] = React.useState(null);
  const [activeFilter, setActiveFilter] = React.useState("ALL");
  const [search, setSearch] = React.useState("");
  const [selectedArticle, setSelectedArticle] = React.useState(D.feed[0]);
  const clock = useClock();

  const filtered = React.useMemo(() => {
    let list = D.feed;
    if (activeFilter !== "ALL") list = list.filter(x => x.category === activeFilter);
    if (activeTag) list = list.filter(x => x.tags.includes(activeTag));
    if (search) list = list.filter(x => x.title.toLowerCase().includes(search.toLowerCase()));
    return list;
  }, [activeFilter, activeTag, search]);

  return (
    <div style={{ background: "var(--bg)", minHeight: "100vh", fontFamily: "var(--font-mono)", fontSize: 12 }}>
      {/* ==== Top Command Bar ==== */}
      <div style={{ background: "var(--bg-2)", borderBottom: "1px solid var(--rule)", padding: "6px 16px", display: "flex", alignItems: "center", gap: 16, fontSize: 11 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--accent)", fontWeight: 700, letterSpacing: 1 }}>
          <span style={{ width: 20, height: 20, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "var(--accent)", color: "var(--bg)", fontSize: 10, fontWeight: 800 }}>V</span>
          VOLPRED
          <span style={{ color: "var(--ink-3)", fontWeight: 400 }}>v4.128</span>
        </div>
        <div style={{ display: "flex", gap: 2 }}>
          {["DASH", "FEED", "STRAT", "PAPERS", "Q&A", "BACKTEST", "API"].map((t, i) => (
            <button key={t} style={{ padding: "4px 12px", background: i === 1 ? "var(--accent)" : "transparent", color: i === 1 ? "var(--bg)" : "var(--ink-2)", fontSize: 11, fontWeight: 600, letterSpacing: 1 }}>{t}</button>
          ))}
        </div>
        <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, maxWidth: 400, marginLeft: 20 }}>
          <span style={{ color: "var(--ink-3)" }}>⌘</span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="search GARCH VIX FOMC..."
            style={{ flex: 1, background: "var(--surface)", border: "1px solid var(--rule)", color: "var(--ink)", padding: "4px 8px", fontFamily: "var(--font-mono)", fontSize: 11 }} />
        </div>
        <div style={{ display: "flex", gap: 16, alignItems: "center", color: "var(--ink-3)", fontSize: 11 }}>
          <span><span className="live-dot" /> LIVE</span>
          <span>{formatDate(clock)} {formatTime(clock)}</span>
          <span>UTC+8</span>
          <button style={{ padding: "2px 8px", border: "1px solid var(--rule)", color: "var(--ink-2)" }}>◐ THEME</button>
        </div>
      </div>

      {/* ==== Scrolling Ticker ==== */}
      <div style={{ background: "var(--surface)", borderBottom: "1px solid var(--rule)", padding: "6px 0", overflow: "hidden" }}>
        <div style={{ display: "flex", gap: 32, whiteSpace: "nowrap", animation: "ticker 60s linear infinite", fontSize: 11 }}>
          {[...Array(2)].map((_, k) => (
            <React.Fragment key={k}>
              {[
                { s: "SPY", p: 710.14, c: 1.20, mono: true },
                { s: "0050.TW", p: 85.00, c: 1.02 },
                { s: "GLD", p: 445.93, c: 1.32 },
                { s: "VIX", p: 17.48, c: -0.42, regime: "NORMAL" },
                { s: "GARCH-σ", p: 12.4, c: 0, suffix: "%" },
                { s: "DXY", p: 103.24, c: -0.18 },
                { s: "TNX", p: 4.28, c: 0.02, suffix: "%" },
                { s: "BTC", p: 87324, c: 2.14 },
                { s: "0050 除息", p: "T-32", c: 0, note: "NEXT" },
                { s: "FOMC", p: "T-11", c: 0, note: "04/29" },
                { s: "TSMC ER", p: "DONE", c: 0, note: "Q1 CAPEX 56B" },
              ].map((t, i) => (
                <span key={`${k}-${i}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <span style={{ color: "var(--ink-3)" }}>{t.s}</span>
                  <span style={{ color: "var(--ink)" }}>{t.p}{t.suffix || ""}</span>
                  {t.c !== 0 && <span style={{ color: t.c > 0 ? "var(--positive)" : "var(--negative)" }}>{t.c > 0 ? "▲" : "▼"}{Math.abs(t.c)}%</span>}
                  {t.note && <span style={{ color: "var(--amber)" }}>· {t.note}</span>}
                  {t.regime && <span style={{ color: "var(--amber)" }}>· {t.regime}</span>}
                </span>
              ))}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* ==== Main 3-pane Dashboard ==== */}
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr 400px", height: "calc(100vh - 72px)", overflow: "hidden" }}>

        {/* Left Panel */}
        <aside style={{ background: "var(--bg-2)", borderRight: "1px solid var(--rule)", overflowY: "auto" }}>
          {/* Markets */}
          <TerminalPanel title="MARKETS" subtitle="4 ASSETS · REAL-TIME">
            {[
              { s: "SPY", p: 710.14, c: 1.20, sl: D.vixHistory.slice(-30) },
              { s: "0050.TW", p: 85.00, c: 1.02, sl: D.vixHistory.slice(-30).map(v => v + 2) },
              { s: "GLD", p: 445.93, c: 1.32, sl: D.vixHistory.slice(-30).map(v => 22 - v * 0.3) },
              { s: "VIX", p: 17.48, c: -0.42, sl: D.vixHistory.slice(-30), highlight: true },
            ].map(m => (
              <div key={m.s} style={{ padding: "8px 12px", borderBottom: "1px solid var(--rule)", display: "grid", gridTemplateColumns: "60px 60px 1fr", alignItems: "center", gap: 8, background: m.highlight ? "color-mix(in srgb, var(--accent) 5%, transparent)" : "transparent" }}>
                <span style={{ fontWeight: 700, color: m.highlight ? "var(--accent)" : "var(--ink)" }}>{m.s}</span>
                <span style={{ color: "var(--ink-2)" }}>{m.p}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "flex-end" }}>
                  <Sparkline data={m.sl} width={60} height={18} stroke={m.c > 0 ? "var(--positive)" : "var(--negative)"} fill={m.c > 0 ? "var(--positive)" : "var(--negative)"} />
                  <span style={{ color: m.c > 0 ? "var(--positive)" : "var(--negative)", fontSize: 10, minWidth: 40, textAlign: "right" }}>{m.c > 0 ? "+" : ""}{m.c}%</span>
                </div>
              </div>
            ))}
          </TerminalPanel>

          {/* Strategy Alloc */}
          <TerminalPanel title="STRATEGY" subtitle="2026-04-19 · GARCH σ=12.4%">
            {D.strategies.map((s, i) => (
              <div key={i} style={{ padding: "8px 12px", borderBottom: "1px solid var(--rule)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span style={{ color: "var(--ink-2)", fontSize: 11 }}>{s.name}</span>
                  <span style={{ color: "var(--accent)", fontWeight: 700, fontSize: 11 }}>{s.weight}%</span>
                </div>
                <div style={{ height: 3, background: "var(--rule)", display: "flex" }}>
                  <div style={{ width: `${s.weight}%`, background: "var(--accent)" }} />
                  {s.second && <div style={{ width: `${s.second}%`, background: "var(--amber)" }} />}
                </div>
                <div style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 2 }}>{s.asset} · CASH {s.cash}%</div>
              </div>
            ))}
          </TerminalPanel>

          {/* Filters */}
          <TerminalPanel title="FILTER" subtitle={`${filtered.length}/${D.feed.length}`}>
            <div style={{ padding: 12 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, marginBottom: 12 }}>
                {["ALL", "研究", "一般讀者", "每日建議"].map(cat => (
                  <button key={cat} onClick={() => setActiveFilter(cat)} style={{
                    padding: "6px 8px",
                    background: activeFilter === cat ? "var(--accent)" : "transparent",
                    color: activeFilter === cat ? "var(--bg)" : "var(--ink-2)",
                    border: "1px solid var(--rule)",
                    fontSize: 10, letterSpacing: 0.5, fontWeight: 600,
                  }}>{cat === "ALL" ? "ALL" : cat === "研究" ? "RSRCH" : cat === "一般讀者" ? "PUBLIC" : "DAILY"}</button>
                ))}
              </div>
              <div style={{ fontSize: 10, color: "var(--ink-3)", marginBottom: 6 }}>TAGS</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                {D.topTags.slice(0, 12).map(t => (
                  <button key={t.name} onClick={() => setActiveTag(activeTag === t.name ? null : t.name)} style={{
                    padding: "2px 6px",
                    fontSize: 10,
                    background: activeTag === t.name ? "var(--accent)" : "transparent",
                    color: activeTag === t.name ? "var(--bg)" : "var(--ink-2)",
                    border: "1px solid var(--rule)",
                  }}>{t.name} <sup style={{ opacity: 0.6 }}>{t.count}</sup></button>
                ))}
              </div>
            </div>
          </TerminalPanel>
        </aside>

        {/* Center Panel */}
        <main style={{ overflowY: "auto", background: "var(--bg)" }}>
          {/* Hero */}
          <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--rule)", background: "linear-gradient(135deg, var(--surface) 0%, var(--bg-2) 100%)" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
              <div>
                <div style={{ color: "var(--accent)", fontSize: 10, letterSpacing: 2, marginBottom: 6 }}>
                  ▸▸▸ AI-OPERATED VOLATILITY RESEARCH PLATFORM
                </div>
                <h1 style={{ fontSize: 34, fontWeight: 800, letterSpacing: -0.8, marginBottom: 10, color: "var(--ink)", fontFamily: "var(--font-mono)", lineHeight: 1.1 }}>
                  100% AI-autonomous quant research.<br/>
                  <span style={{ color: "var(--accent)" }}>From hypothesis → experiment → paper.</span>
                </h1>
                <p style={{ fontSize: 13, color: "var(--ink-2)", maxWidth: 640, lineHeight: 1.5 }}>
                  全球首個由 AI 自主設計實驗、執行回測、撰寫論文的投資研究平台。三市場（SPY / 0050 / GLD）× 四類模型（GARCH / HAR / MIDAS / GAS-t）× 587 篇已發表研究。
                </p>
                <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                  <button style={{ padding: "8px 16px", background: "var(--accent)", color: "var(--bg)", fontWeight: 700, letterSpacing: 1, fontSize: 11 }}>▶ EXPLORE FEED</button>
                  <button style={{ padding: "8px 16px", background: "transparent", color: "var(--ink)", border: "1px solid var(--rule-strong)", fontWeight: 700, letterSpacing: 1, fontSize: 11 }}>◉ LIVE DASHBOARD</button>
                  <button style={{ padding: "8px 16px", background: "transparent", color: "var(--ink-2)", border: "1px solid var(--rule)", fontSize: 11 }}>$ API.docs</button>
                </div>
              </div>
              <TerminalReadout data={D} />
            </div>
          </div>

          {/* Live heatmap banner */}
          <div style={{ padding: "12px 24px", borderBottom: "1px solid var(--rule)", background: "var(--bg-2)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 10, color: "var(--ink-3)", letterSpacing: 1 }}>
              <span>RESEARCH OUTPUT · LAST 90 DAYS</span>
              <span>ROW: WEEK · COL: WEEKDAY · COLOR: #PUBLISHED</span>
            </div>
            <ResearchHeatmap />
          </div>

          {/* Feed */}
          <div style={{ padding: "16px 24px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, paddingBottom: 8, borderBottom: "1px solid var(--rule-strong)" }}>
              <span style={{ color: "var(--accent)", fontWeight: 700, letterSpacing: 1 }}>▸ RESEARCH FEED</span>
              <span style={{ color: "var(--ink-3)", fontSize: 10 }}>({filtered.length} items)</span>
              <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--ink-3)" }}>sort: LATEST ▾</span>
            </div>

            {filtered.map((a, i) => (
              <TerminalArticleRow key={a.id} article={a} index={i} selected={selectedArticle?.id === a.id} onSelect={() => setSelectedArticle(a)} />
            ))}
          </div>
        </main>

        {/* Right Panel */}
        <aside style={{ background: "var(--bg-2)", borderLeft: "1px solid var(--rule)", overflowY: "auto" }}>
          {selectedArticle && <TerminalPreview article={selectedArticle} />}

          <TerminalPanel title="PAPERS" subtitle="WORKING">
            {D.papers.map(p => (
              <div key={p.id} style={{ padding: "10px 12px", borderBottom: "1px solid var(--rule)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span style={{ color: "var(--accent)", fontSize: 10, fontWeight: 700 }}>PAPER {p.id}/{D.papers.length} · {p.year}</span>
                  <span style={{ fontSize: 10, color: p.status === "published" ? "var(--positive)" : p.status === "revision" ? "var(--amber)" : "var(--ink-3)" }}>● {p.status.toUpperCase()}</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--ink)", lineHeight: 1.35, fontWeight: 500 }}>{p.title}</div>
                <div style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 4 }}>cited: {p.citations} · {p.authors.join(", ")}</div>
              </div>
            ))}
          </TerminalPanel>

          <TerminalPanel title="Q&A" subtitle={`${D.questions.length} ACTIVE`}>
            {D.questions.slice(0, 3).map(q => (
              <div key={q.id} style={{ padding: "10px 12px", borderBottom: "1px solid var(--rule)" }}>
                <div style={{ fontSize: 11, color: "var(--ink)", lineHeight: 1.3, marginBottom: 6, fontWeight: 500 }}>Q. {q.question}</div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--ink-3)" }}>
                  <span>@{q.author}</span>
                  <span style={{ color: "var(--accent)" }}>▲{q.votes} · {q.answers} ans</span>
                </div>
              </div>
            ))}
          </TerminalPanel>

          <TerminalPanel title="NETWORK" subtitle="TAG RELATIONS">
            <TagNetwork tags={D.topTags.slice(0, 10)} />
          </TerminalPanel>
        </aside>
      </div>

      <style>{`
        @keyframes ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }
      `}</style>
    </div>
  );
}

// ================== Terminal Panel ==================
function TerminalPanel({ title, subtitle, children }) {
  return (
    <div style={{ marginBottom: 1 }}>
      <div style={{ padding: "6px 12px", background: "var(--surface)", borderBottom: "1px solid var(--rule)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ color: "var(--accent)", fontSize: 10, fontWeight: 700, letterSpacing: 1.5 }}>[ {title} ]</span>
        {subtitle && <span style={{ color: "var(--ink-3)", fontSize: 10 }}>{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

// ================== Terminal Readout (big nums) ==================
function TerminalReadout({ data }) {
  const d = data.market;
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--rule)", padding: 14, minWidth: 280 }}>
      <div style={{ fontSize: 10, color: "var(--accent)", letterSpacing: 1.5, marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
        <span>▌ VIX REGIME</span>
        <span style={{ color: "var(--amber)" }}>⬤ NORMAL</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 9, color: "var(--ink-3)", letterSpacing: 1 }}>VIX.CBOE</div>
          <div style={{ fontSize: 32, fontWeight: 800, color: "var(--ink)", letterSpacing: -1 }}><TickerNumber value={d.vix} /></div>
          <div style={{ fontSize: 10, color: "var(--negative)" }}>▼ 0.42 (-2.35%)</div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: "var(--ink-3)", letterSpacing: 1 }}>GARCH σ</div>
          <div style={{ fontSize: 32, fontWeight: 800, color: "var(--ink)", letterSpacing: -1 }}><TickerNumber value={d.garchSigma} decimals={1} suffix="%" /></div>
          <div style={{ fontSize: 10, color: "var(--ink-3)" }}>annualized</div>
        </div>
      </div>
      <VixGauge value={d.vix} />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--ink-4)", marginTop: 4 }}>
        <span>0</span><span>13</span><span>20</span><span>30</span><span>50</span>
      </div>
    </div>
  );
}

// ================== Terminal Article Row ==================
function TerminalArticleRow({ article, index, selected, onSelect }) {
  const catColor = {
    "研究": "var(--accent)",
    "一般讀者": "var(--blue)",
    "每日建議": "var(--amber)",
  }[article.category] || "var(--ink-3)";
  return (
    <div onClick={onSelect} style={{
      padding: "10px 12px",
      borderLeft: `3px solid ${selected ? catColor : "transparent"}`,
      background: selected ? "color-mix(in srgb, var(--accent) 6%, transparent)" : "transparent",
      borderBottom: "1px solid var(--rule)",
      cursor: "pointer",
      display: "grid",
      gridTemplateColumns: "40px 90px 70px 1fr auto",
      gap: 12,
      alignItems: "center",
      fontSize: 12,
    }}>
      <span style={{ color: "var(--ink-4)", fontSize: 10 }}>{String(index + 1).padStart(3, '0')}</span>
      <span style={{ color: "var(--ink-3)", fontSize: 10 }}>{article.date}</span>
      <span style={{ color: catColor, fontSize: 10, fontWeight: 700, letterSpacing: 0.5 }}>● {article.category === "研究" ? "RSRCH" : article.category === "一般讀者" ? "PUBLIC" : "DAILY"}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ color: "var(--ink)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{article.title}</div>
        <div style={{ fontSize: 10, color: "var(--ink-3)", marginTop: 2, display: "flex", gap: 8 }}>
          <span>@{article.author}</span>
          <span>·</span>
          <span>{article.ago}</span>
          <span>·</span>
          <span>{article.tags.slice(0, 3).join(" · ")}</span>
        </div>
      </div>
      <span style={{ color: "var(--ink-3)", fontSize: 10, fontFamily: "var(--font-mono)" }}>{article.readTime}m</span>
    </div>
  );
}

// ================== Terminal Preview ==================
function TerminalPreview({ article }) {
  return (
    <TerminalPanel title="PREVIEW" subtitle={`ID: ${article.id.slice(-8).toUpperCase()}`}>
      <div style={{ padding: 14 }}>
        <div style={{ fontSize: 10, color: "var(--accent)", letterSpacing: 1, marginBottom: 6 }}>
          {article.category === "研究" ? "▸ RESEARCH" : article.category === "一般讀者" ? "▸ PUBLIC" : "▸ DAILY"} · {article.date} · {article.time}
        </div>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)", lineHeight: 1.35, marginBottom: 8 }}>
          {article.title}
        </div>
        {article.subtitle && <div style={{ fontSize: 12, color: "var(--ink-2)", fontStyle: "italic", marginBottom: 10, lineHeight: 1.4 }}>{article.subtitle}</div>}
        <div style={{ fontSize: 11, color: "var(--ink-2)", lineHeight: 1.55, marginBottom: 12 }}>{article.abstract}</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 12 }}>
          {article.tags.map(t => (
            <span key={t} style={{ fontSize: 10, padding: "2px 6px", border: "1px solid var(--rule)", color: "var(--ink-3)" }}>#{t}</span>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 10 }}>
          <div style={{ padding: 6, background: "var(--surface)", border: "1px solid var(--rule)" }}>
            <div style={{ color: "var(--ink-3)" }}>AUTHOR</div>
            <div style={{ color: "var(--ink)", fontWeight: 600 }}>@{article.author}</div>
          </div>
          <div style={{ padding: 6, background: "var(--surface)", border: "1px solid var(--rule)" }}>
            <div style={{ color: "var(--ink-3)" }}>READ</div>
            <div style={{ color: "var(--ink)", fontWeight: 600 }}>{article.readTime} min</div>
          </div>
        </div>
        <button style={{ width: "100%", marginTop: 10, padding: "8px 12px", background: "var(--accent)", color: "var(--bg)", fontWeight: 700, letterSpacing: 1, fontSize: 11 }}>▶ OPEN FULL ARTICLE</button>
      </div>
    </TerminalPanel>
  );
}

// ================== Research Heatmap ==================
function ResearchHeatmap() {
  const weeks = 13;
  const cells = Array.from({ length: weeks * 7 }, (_, i) => {
    const seed = i * 7919 % 11;
    return { count: seed, date: `2026-W${Math.floor(i / 7) + 1}-${(i % 7) + 1}` };
  });
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${weeks}, 1fr)`, gap: 2, maxWidth: 600 }}>
      {Array.from({ length: 7 }).map((_, row) => (
        Array.from({ length: weeks }).map((_, col) => {
          const c = cells[col * 7 + row];
          const intensity = c.count / 10;
          return (
            <div key={`${row}-${col}`} title={`${c.date}: ${c.count} items`} style={{
              aspectRatio: "1",
              background: c.count === 0 ? "var(--rule)" : `color-mix(in srgb, var(--accent) ${intensity * 100}%, transparent)`,
              border: "1px solid var(--bg-2)",
            }} />
          );
        })
      ))}
    </div>
  );
}

// ================== Tag Network ==================
function TagNetwork({ tags }) {
  const W = 370, H = 280;
  const nodes = tags.map((t, i) => {
    const angle = (i / tags.length) * Math.PI * 2;
    const r = 60 + (i % 3) * 30;
    return { ...t, x: W/2 + Math.cos(angle) * r, y: H/2 + Math.sin(angle) * r, size: Math.min(20, 6 + t.count / 40) };
  });
  return (
    <div style={{ padding: 8 }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%" }}>
        {/* Links */}
        {nodes.map((n, i) => nodes.slice(i + 1).map((m, j) => {
          if ((i + j) % 3 !== 0) return null;
          return <line key={`${i}-${j}`} x1={n.x} y1={n.y} x2={m.x} y2={m.y} stroke="var(--rule)" strokeWidth="0.5" />;
        }))}
        {/* Nodes */}
        {nodes.map(n => (
          <g key={n.name}>
            <circle cx={n.x} cy={n.y} r={n.size} fill="var(--accent)" opacity="0.15" />
            <circle cx={n.x} cy={n.y} r={n.size * 0.5} fill="var(--accent)" />
            <text x={n.x} y={n.y + n.size + 10} textAnchor="middle" fontSize="9" fill="var(--ink-2)" fontFamily="var(--font-mono)">{n.name}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

Object.assign(window, { V2Terminal });
