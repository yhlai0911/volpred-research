// Shared components — 市場數據、Sparkline、Hero 等

// ============ Sparkline ============
function Sparkline({ data, width = 80, height = 24, stroke = "currentColor", fill, className = "" }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);
  const points = data.map((v, i) => `${i * stepX},${height - ((v - min) / range) * height}`).join(" ");
  const areaPoints = `0,${height} ${points} ${width},${height}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className} style={{ overflow: "visible" }}>
      {fill && <polygon points={areaPoints} fill={fill} opacity="0.15" />}
      <polyline points={points} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ============ TickerNumber - animated count ============
function TickerNumber({ value, decimals = 2, prefix = "", suffix = "", className = "" }) {
  const [display, setDisplay] = React.useState(value);
  const prev = React.useRef(value);
  React.useEffect(() => {
    const from = prev.current;
    const to = value;
    const duration = 600;
    const start = performance.now();
    let raf;
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (to - from) * eased);
      if (t < 1) raf = requestAnimationFrame(step);
      else prev.current = to;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <span className={`ticker-num ${className}`}>{prefix}{display.toFixed(decimals)}{suffix}</span>;
}

// ============ Clock ============
function useClock() {
  const [t, setT] = React.useState(new Date());
  React.useEffect(() => {
    const id = setInterval(() => setT(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return t;
}

function formatTime(d) {
  return d.toTimeString().slice(0, 8);
}

function formatDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

// ============ VIX Regime Bar ============
function VixGauge({ value, className = "" }) {
  // 0-10 low, 10-20 normal, 20-30 elevated, 30+ panic
  const pct = Math.min(100, (value / 50) * 100);
  const regime = value < 13 ? "low" : value < 20 ? "normal" : value < 30 ? "elevated" : "panic";
  const colors = {
    low: "var(--positive, #2d5a3f)",
    normal: "var(--ink-3)",
    elevated: "var(--accent-2, #c9a961)",
    panic: "var(--negative, #8b1e1e)",
  };
  return (
    <div className={className} style={{ width: "100%" }}>
      <div style={{ height: 4, background: "var(--rule)", position: "relative", overflow: "hidden" }}>
        <div style={{
          position: "absolute", left: 0, top: 0, bottom: 0,
          width: `${pct}%`, background: colors[regime],
          transition: "width 600ms cubic-bezier(.2,.8,.2,1)",
        }} />
        {/* Regime markers */}
        {[13, 20, 30].map(m => (
          <div key={m} style={{
            position: "absolute", left: `${(m/50)*100}%`, top: 0, bottom: 0,
            width: 1, background: "var(--bg)",
          }} />
        ))}
      </div>
    </div>
  );
}

// ============ Category Badge ============
function CategoryBadge({ category, variant = "default" }) {
  const map = {
    "研究": { label: "RESEARCH", color: "var(--accent)" },
    "一般讀者": { label: "PUBLIC", color: "var(--accent-2, var(--ink-2))" },
    "每日建議": { label: "DAILY", color: "var(--ink-3)" },
  };
  const c = map[category] || { label: category, color: "var(--ink-3)" };
  if (variant === "dot") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 10, fontFamily: "var(--font-mono)", color: c.color, letterSpacing: 1, textTransform: "uppercase" }}>
        <span style={{ width: 5, height: 5, background: c.color, borderRadius: "50%" }} />
        {c.label}
      </span>
    );
  }
  return (
    <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: c.color, letterSpacing: 1.5, fontWeight: 600, textTransform: "uppercase" }}>
      {c.label}
    </span>
  );
}

// ============ Logo/Mark ============
function VolPredMark({ size = 28, theme = "editorial" }) {
  // A stylized volatility wave + V shape
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" fill="currentColor" opacity="0.08" rx="2" />
      <path d="M4 20 L8 14 L12 22 L16 8 L20 18 L24 12 L28 20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <circle cx="16" cy="8" r="1.5" fill="currentColor" />
    </svg>
  );
}

Object.assign(window, { Sparkline, TickerNumber, useClock, formatTime, formatDate, VixGauge, CategoryBadge, VolPredMark });
