-- Create papers table for the paper page
CREATE TABLE IF NOT EXISTS papers (
  id serial PRIMARY KEY,
  title text NOT NULL,
  authors text NOT NULL,
  abstract text,
  status text NOT NULL DEFAULT 'working',
  target_journal text,
  pdf_url text,
  pages integer,
  figures integer,
  tables integer,
  citations integer,
  contributions text[],
  keywords text[],
  display_order integer DEFAULT 0,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- Insert 3 papers
INSERT INTO papers (title, authors, abstract, status, target_journal, pdf_url, pages, figures, tables, citations, contributions, keywords, display_order) VALUES
(
  'Leverage Direction Matters: GJR-GARCH Volatility Targeting for Risk Management',
  'Yi-Hao Lai, VolPred Research System',
  'This paper demonstrates that the direction of leverage effect (GJR gamma) determines optimal volatility model selection and VT strategy effectiveness across asset classes.',
  'working',
  'Journal of Banking and Finance',
  '/paper/leverage-direction-matters.pdf',
  56, 7, 12, 30,
  ARRAY['GJR-GARCH superiority for equity vol', 'Gamma-mechanism for VT', 'Cross-asset model selection rule'],
  ARRAY['GJR-GARCH', 'volatility targeting', 'leverage effect', 'VaR'],
  1
),
(
  'Volatility Targeting in Taiwan: VIX as Universal Proxy and Time-Zone Information Transmission',
  'Yi-Hao Lai, VolPred Research System',
  'We show US VIX serves as an effective proxy for Taiwan market volatility targeting, achieving significant MDD reduction. Cross-timezone momentum signals are not implementable due to opening auction efficiency.',
  'working',
  'Pacific-Basin Finance Journal',
  '/paper/taiwan-vt-tz-arbitrage.pdf',
  28, 5, 8, 14,
  ARRAY['US VIX proxy for Taiwan VT', 'TZ information transmission', 'Opening auction efficiency'],
  ARRAY['Taiwan', '0050.TW', 'VIX', 'time-zone', 'information transmission'],
  2
),
(
  'Is Volatility Targeting Just Trend Following? Decomposing the Benefits Through the Leverage Effect',
  'Yi-Hao Lai, VolPred Research System',
  'We decompose VT benefits into two channels: a trend-following channel (32% of Sharpe, driven by leverage effect) and a VIX position-sizing channel (96% of MDD protection). N=22 assets, FF5+MOM+BAB controls.',
  'working',
  'Finance Research Letters',
  '/paper/vt-trend-following.pdf',
  24, 0, 5, 18,
  ARRAY['Dual-channel VT decomposition', 'Leverage effect as TSMOM link (r=0.564)', 'VIX universal MDD insurance (13 markets)'],
  ARRAY['volatility targeting', 'trend following', 'TSMOM', 'leverage effect', 'MDD'],
  3
);

NOTIFY pgrst, 'reload schema';
