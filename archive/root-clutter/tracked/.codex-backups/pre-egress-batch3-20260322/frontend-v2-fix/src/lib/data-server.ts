import { promises as fs } from 'fs';
import path from 'path';
import { unstable_cache } from 'next/cache';
import { createServiceClient } from './supabase-server';
import {
  buildStrategyPerformanceSeries,
  compressStrategyValues,
  extractRealizedStrategyReturns,
} from './strategy-performance';
import type {
  BookmarkedArticleItem,
  FeedItem,
  FeedListResponse,
  FeedTagCount,
  JsonObject,
  JsonValue,
  LinkedArticle,
  PaperTradingMap,
  PortfolioOverviewResponse,
  PortfolioOverviewStrategy,
  PaperTradingStrategy,
  QuestionItem,
  RiskForecast,
  StrategyMetrics,
  StrategyOverview,
  StrategySignal,
  } from './api';

type SupabaseClient = ReturnType<typeof createServiceClient>;
const STRATEGY_METRICS_CACHE_VERSION = 2;

type ArticleSummaryRow = {
  id: string;
  slug: string;
  title: string;
  excerpt: string | null;
  audience: string | null;
  phase: string | null;
  status: string;
  category: string;
  proposer: string | null;
  published_at: string;
  created_at: string | null;
  details: JsonObject | null;
};

type ArticleDetailRow = ArticleSummaryRow & {
  summary: string | null;
  content: string | null;
  description: string | null;
  analysis: string | null;
  metrics: JsonObject | null;
  ranking: JsonObject[] | null;
  experiment_id: string | null;
  experiment_ids: string[] | null;
};

type FeedRpcRow = {
  article_id: string;
  slug: string;
  title: string;
  excerpt: string | null;
  audience: string | null;
  phase: string | null;
  status: string;
  category: string;
  proposer: string | null;
  published_at: string;
  created_at: string | null;
  details: JsonObject | null;
  tags: string[] | null;
  view_count: number | null;
  likes: number | null;
  total_count: number | null;
};

type ArticleTagLink = {
  article_id: string;
  tags: { name: string | null } | Array<{ name: string | null }> | null;
};

type ArticleStatsRow = {
  article_id: string;
  view_count: number | null;
  likes: number | null;
};

type FeedOptions = {
  audience?: string;
  search?: string;
  tag?: string;
  limit?: number;
  offset?: number;
};

type ArticleStats = {
  view_count: number;
  likes: number;
};

type MemoryEntry = {
  content: JsonValue;
};

type ExperimentEntry = {
  experiment_id?: string;
  model_name?: string;
  asset?: string;
  metrics?: {
    qlike?: number;
  };
};

type QuestionRow = {
  id: string;
  created_at: string | null;
  answered_at: string | null;
  user_id: string | null;
  question: string;
  priority: string | null;
  status: string | null;
  answer: string | null;
  proposer: string | null;
  score: number | null;
  current_rank?: number | null;
  score_breakdown?: JsonObject | null;
  prev_rank?: number | null;
};

type QuestionArticleJoinRow = {
  question_id: string;
  article_id: string;
  article: { id: string; slug: string; title: string } | Array<{ id: string; slug: string; title: string }> | null;
};

type ArticleReactionRow = {
  article_id: string;
  created_at: string;
};

type LocalQuestionRow = {
  id?: string;
  timestamp?: string;
  created_at?: string;
  answered_at?: string | null;
  user_id?: string | null;
  question?: string;
  priority?: string | null;
  status?: string | null;
  answer?: string | null;
  proposer?: string | null;
  score?: number | null;
  current_rank?: number | null;
  score_breakdown?: JsonObject | null;
  prev_rank?: number | null;
  feed_articles?: string[] | null;
};

type LocalFeedRow = {
  id?: string;
  title?: string;
  description?: string | null;
  audience?: string | null;
  phase?: string | null;
  status?: string | null;
  category?: string | null;
  published_at?: string | null;
  created_at?: string | null;
  details?: JsonObject | null;
  tags?: string[] | null;
  summary?: string | null;
  content?: string | null;
  analysis?: string | null;
  metrics?: JsonObject | null;
  ranking?: JsonObject[] | null;
  experiment_id?: string | null;
  experiment_ids?: string[] | null;
};

type LocalFeedEntry = {
  article: ArticleSummaryRow;
  tags: string[];
  searchText: string;
};

type LocalPaperTradingSnapshotEntry = {
  entries?: PaperTradeEntry[] | null;
  initial_capital?: number | null;
  stats?: JsonObject | null;
};

type LocalStrategyMarketSnapshot = {
  updated_at: string | null;
  sigma_ann: number | null;
  vix_level: number | null;
  spy_close: number | null;
  gld_close: number | null;
  tw50_close: number | null;
  strategy_weights: Record<string, Record<string, number>>;
};

type StrategySignalRow = {
  id: number;
  strategy_name: string;
  strategy_key: string;
  description?: string | null;
  howto?: string | null;
  color?: string | null;
  weights: JsonValue;
  vix_level: number | null;
  sigma_ann: number | null;
  updated_at: string;
  is_active: boolean;
  articles?: string[] | null;
};

type StrategyMetricsCacheRow = {
  strategy: string;
  display_name: string;
  metrics: JsonObject | null;
  sparkline: number[] | null;
  latest_trade_date: string | null;
  updated_at: string | null;
};

type StrategyMetricsCachePayload = {
  display_name: string;
  metrics: StrategyMetrics;
  sparkline: number[];
  latest_trade_date: string | null;
  updated_at: string | null;
};

type PaperTradeEntry = {
  trade_date?: string | null;
  portfolio_return?: number | null;
  actual_spy_return?: number | null;
  actual_next_day_return?: number | null;
  recommended_weight?: number | null;
  weights?: JsonObject | null;
  cash_weight?: number | null;
  spy_close?: number | null;
  gld_close?: number | null;
  sigma_spy_ann?: number | null;
  sigma_gjr_annual?: number | null;
  tw50_close?: number | null;
  nk225_close?: number | null;
  '0050_close'?: number | null;
  data_date?: string | null;
  date?: string | null;
  prediction_date?: string | null;
  action?: string | null;
  portfolio?: JsonObject | null;
  [key: string]: JsonValue | undefined;
};

type PaperTradeRow = {
  strategy: string;
  entry: PaperTradeEntry | null;
  trade_date: string;
};

type SyncPaperTradingStrategy = {
  entries?: PaperTradeEntry[] | null;
};

type SyncPaperTradingPayload = Record<string, SyncPaperTradingStrategy | null | undefined>;

const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;
const RELATED_LIMIT = 3;
const RELATED_CANDIDATE_LIMIT = 60;
const COMMON_START = '2023-01-04';

const FEED_ARTICLE_SELECT =
  'id, slug, title, excerpt, audience, phase, status, category, proposer, published_at, created_at, details';

const FEED_RPC_NAME = 'feed_page';
const FEED_TAG_COUNTS_RPC_NAME = 'feed_tag_counts';

const TW_TAGS = new Set(['台股', '0050.tw', '台灣', 'taiex', '0050']);
const US_TAGS = new Set(['spy', 'qqq', 'gld', 'tlt', 'vix', '美股', 's&p 500']);
const DEFAULT_STRATEGY_COLOR = '#6B7280';

const LOCAL_STRATEGY_METADATA: Record<string, { howto: string; color: string }> = {
  slow_vt: { howto: 'GARCH sigma target on SPY with cash buffer', color: '#10B981' },
  risk_parity: { howto: 'Balance SPY and GLD by forecast risk', color: '#3B82F6' },
  simple_12vix: { howto: 'Classic 12/VIX single-asset allocation', color: '#8B5CF6' },
  recommended_5050: { howto: 'Recommended 50/50 SPY and GLD risk budget', color: '#F59E0B' },
  'taiwan_8.63vix': { howto: 'Vol-target allocation for 0050.TW', color: '#06B6D4' },
  taiwan_spy_momentum: { howto: 'Cross-market timing between Taiwan and SPY', color: '#EF4444' },
  tz_tw_jp_5050: { howto: 'Taiwan and Japan 50/50 timing basket', color: '#F97316' },
  global_vt_tz: { howto: 'Global SPY GLD Taiwan balanced timing', color: '#A855F7' },
  vix_leading_guard: { howto: 'Use VIX regime to guard 0050.TW exposure', color: '#14B8A6' },
};

let _supabase: SupabaseClient | null = null;

function getSupabase(): SupabaseClient {
  if (!_supabase) _supabase = createServiceClient();
  return _supabase;
}

const supabase = new Proxy({} as SupabaseClient, {
  get(_target, prop) {
    return getSupabase()[prop as keyof SupabaseClient];
  },
});

function clampLimit(limit?: number): number {
  if (!Number.isFinite(limit)) return DEFAULT_LIMIT;
  return Math.min(Math.max(Math.trunc(limit || DEFAULT_LIMIT), 1), MAX_LIMIT);
}

function clampOffset(offset?: number): number {
  if (!Number.isFinite(offset)) return 0;
  return Math.max(Math.trunc(offset || 0), 0);
}

function sanitizeSearchTerm(search?: string): string | undefined {
  const normalized = search
    ?.trim()
    .replace(/[^\p{L}\p{N}\s._-]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  return normalized ? normalized : undefined;
}

function parseTags(tags: string[]): string[] {
  return Array.from(
    new Set(
      tags
        .flatMap((tag) => tag.split(','))
        .map((tag) => tag.trim())
        .filter(Boolean)
    )
  );
}

function normalizeTag(tag: string): string {
  return tag.trim().toLowerCase();
}

function buildSnapshotCandidates(...candidateSegments: string[][]): string[] {
  const seen = new Set<string>();
  return candidateSegments
    .map((segments) => path.resolve(process.cwd(), ...segments))
    .filter((candidate) => {
      if (seen.has(candidate)) return false;
      seen.add(candidate);
      return true;
    });
}

function getFeedSnapshotPaths(): string[] {
  return buildSnapshotCandidates(
    ['..', 'storage', 'reports', 'feed.json'],
    ['storage', 'reports', 'feed.json'],
    ['frontend-v2-fix', 'storage', 'reports', 'feed.json']
  );
}

function getReportSnapshotPaths(slug: string): string[] {
  return buildSnapshotCandidates(
    ['..', 'storage', 'reports', `${slug}.json`],
    ['storage', 'reports', `${slug}.json`],
    ['frontend-v2-fix', 'storage', 'reports', `${slug}.json`]
  );
}

function getRiskForecastSnapshotPaths(): string[] {
  return buildSnapshotCandidates(
    ['..', 'storage', 'risk_forecast.json'],
    ['storage', 'risk_forecast.json'],
    ['frontend-v2-fix', 'storage', 'risk_forecast.json'],
    ['public', 'data', 'risk_forecast.json'],
    ['data', 'risk_forecast.json']
  );
}

function getStrategyMetricsSnapshotPaths(): string[] {
  return buildSnapshotCandidates(
    ['..', 'storage', 'strategy_metrics.json'],
    ['storage', 'strategy_metrics.json'],
    ['data', 'strategy_metrics.json'],
    ['frontend-v2-fix', 'data', 'strategy_metrics.json']
  );
}

function getStrategyArticlesSnapshotPaths(): string[] {
  return buildSnapshotCandidates(
    ['..', 'storage', 'strategy_articles.json'],
    ['storage', 'strategy_articles.json']
  );
}

function getPaperTradingSnapshotPaths(): string[] {
  return buildSnapshotCandidates(
    ['..', 'storage', 'paper_trading.json'],
    ['storage', 'paper_trading.json'],
    ['data', 'paper_trading.json']
  );
}

function isVirtualAudience(audience?: string): audience is 'tw' | 'us' {
  return audience === 'tw' || audience === 'us';
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function roundPercent(value: number): number {
  return Number(value.toFixed(1));
}

function normalizeStrategyWeightsForDisplay(value: unknown): Record<string, number> {
  if (!isJsonObject(value)) return {};

  const rawWeights = Object.fromEntries(
    Object.entries(value)
      .map(([key, entryValue]) => [key, typeof entryValue === 'number' ? entryValue : Number(entryValue)])
      .filter(([, numericValue]) => Number.isFinite(numericValue))
  );

  const numbers = Object.values(rawWeights);
  if (numbers.length === 0) return {};

  const shouldConvertFromFractions = numbers.every((numericValue) => Math.abs(numericValue) <= 1.0001);
  return Object.fromEntries(
    Object.entries(rawWeights).map(([key, numericValue]) => [
      key,
      shouldConvertFromFractions ? roundPercent(numericValue * 100) : roundPercent(numericValue),
    ])
  );
}

function extractProposerFromText(text?: string | null): string | null {
  if (!text) return null;
  const match = text.match(/\[提出:\s*([^\]\s]+)/u);
  return match?.[1] ?? null;
}

function resolveLocalAudience(item: LocalFeedRow): string {
  const detailsAudience = isJsonObject(item.details) && typeof item.details.audience === 'string' ? item.details.audience : null;
  const explicit = item.audience ?? detailsAudience;
  if (explicit && explicit !== 'general') return explicit;

  const phase = (item.phase ?? '').toLowerCase();
  const tags = (item.tags || []).map((tag) => tag.toLowerCase());
  if (phase === 'member_qa' || tags.includes('會員提問')) return 'member_qa';
  if (phase === 'general_content' || phase === 'general_article' || tags.includes('一般讀者')) return 'general';
  if (phase.includes('daily') || tags.includes('daily_update') || tags.includes('每日更新')) return 'daily';
  if (phase.includes('diary') || tags.includes('研究日記')) return 'diary';
  return 'research';
}

function buildExcerpt(value?: string | null): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (!normalized) return null;
  return normalized.length > 200 ? `${normalized.slice(0, 200)}...` : normalized;
}

function normalizeWeights(value: unknown): Record<string, number> {
  if (!isJsonObject(value)) return {};
  return Object.fromEntries(
    Object.entries(value)
      .map(([key, entryValue]) => [key, typeof entryValue === 'number' ? entryValue : Number(entryValue)])
      .filter(([, numericValue]) => Number.isFinite(numericValue))
  );
}

function normalizeLinkedArticles(links: LinkedArticle[]): LinkedArticle[] {
  const deduped = new Map<string, LinkedArticle>();
  for (const link of links) {
    deduped.set(`${link.article_id}:${link.slug}`, link);
  }
  return Array.from(deduped.values());
}

function matchesAudience(audience: string | undefined, article: ArticleSummaryRow, tags: string[]): boolean {
  if (!audience || audience === 'all') return true;
  if (isVirtualAudience(audience)) {
    const normalizedTags = new Set(tags.map(normalizeTag));
    const targetTags = audience === 'tw' ? TW_TAGS : US_TAGS;
    return Array.from(targetTags).some((tag) => normalizedTags.has(tag));
  }
  return article.audience === audience;
}

function buildTagMap(articleIds: string[], tagLinks: ArticleTagLink[]): Record<string, string[]> {
  const tagMap: Record<string, string[]> = Object.fromEntries(articleIds.map((id) => [id, []]));

  for (const link of tagLinks) {
    const linkedTags = Array.isArray(link.tags) ? link.tags : link.tags ? [link.tags] : [];
    const tagNames = linkedTags
      .map((tag) => tag.name)
      .filter((tag): tag is string => Boolean(tag));

    if (tagNames.length === 0) continue;
    tagMap[link.article_id] = parseTags([...(tagMap[link.article_id] || []), ...tagNames]);
  }

  return tagMap;
}

function buildTagCounts(rows: ArticleSummaryRow[], tagMap: Record<string, string[]>): FeedTagCount[] {
  const counts = new Map<string, number>();

  for (const row of rows) {
    for (const tag of tagMap[row.id] || []) {
      counts.set(tag, (counts.get(tag) || 0) + 1);
    }
  }

  return Array.from(counts.entries())
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag, 'zh-Hant'));
}

function buildStatsMap(statsRows: ArticleStatsRow[]): Record<string, ArticleStats> {
  const statsMap: Record<string, ArticleStats> = {};

  for (const row of statsRows) {
    statsMap[row.article_id] = {
      view_count: row.view_count ?? 0,
      likes: row.likes ?? 0,
    };
  }

  return statsMap;
}

function toFeedItem(
  article: ArticleSummaryRow | ArticleDetailRow,
  tags: string[],
  stats?: ArticleStats
): FeedItem {
  return {
    id: article.slug,
    slug: article.slug,
    article_id: article.id,
    title: article.title,
    category: article.category,
    published_at: article.published_at,
    status: article.status,
    created_at: article.created_at ?? undefined,
    summary: 'summary' in article ? article.summary ?? undefined : undefined,
    content: 'content' in article ? article.content ?? undefined : undefined,
    description: 'description' in article ? article.description ?? undefined : undefined,
    analysis: 'analysis' in article ? article.analysis ?? undefined : undefined,
    metrics: 'metrics' in article ? article.metrics ?? undefined : undefined,
    ranking: 'ranking' in article ? article.ranking ?? undefined : undefined,
    excerpt: article.excerpt ?? undefined,
    audience: article.audience ?? undefined,
    phase: article.phase ?? undefined,
    proposer: article.proposer ?? undefined,
    details: article.details ?? undefined,
    experiment_id: 'experiment_id' in article ? article.experiment_id ?? undefined : undefined,
    experiment_ids: 'experiment_ids' in article ? article.experiment_ids ?? undefined : undefined,
    tags,
    view_count: stats?.view_count ?? 0,
    likes: stats?.likes ?? 0,
  };
}

function toFeedItemFromRpcRow(row: FeedRpcRow): FeedItem {
  return {
    id: row.slug,
    slug: row.slug,
    article_id: row.article_id,
    title: row.title,
    category: row.category,
    published_at: row.published_at,
    status: row.status,
    created_at: row.created_at ?? undefined,
    excerpt: row.excerpt ?? undefined,
    audience: row.audience ?? undefined,
    phase: row.phase ?? undefined,
    proposer: row.proposer ?? undefined,
    details: row.details ?? undefined,
    tags: parseTags(row.tags || []),
    view_count: row.view_count ?? 0,
    likes: row.likes ?? 0,
  };
}

function tokenizeTitle(title: string): string[] {
  return title
    .toLowerCase()
    .split(/[\s,.:;!?()（）/\-_\u3000]+/)
    .filter((token) => token.length >= 2);
}

function extractQuestionIds(details?: JsonObject | null): string[] {
  if (!details) return [];

  const ids = new Set<string>();
  const single = details.question_id;
  if (typeof single === 'string' && single) ids.add(single);

  const multiple = details.question_ids;
  if (Array.isArray(multiple)) {
    for (const value of multiple) {
      if (typeof value === 'string' && value) ids.add(value);
    }
  }

  return Array.from(ids);
}

function extractArticleIdentifier(articleRef: unknown): string | null {
  return typeof articleRef === 'string' && articleRef ? articleRef : null;
}

function isMissingCapabilityError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const message = 'message' in error && typeof error.message === 'string' ? error.message : '';
  return (
    message.includes('Could not find the function') ||
    message.includes('does not exist') ||
    message.includes('relation') ||
    message.includes('schema cache')
  );
}

async function fetchArticleSummaries(options?: Pick<FeedOptions, 'audience' | 'search'>): Promise<ArticleSummaryRow[]> {
  let query = supabase
    .from('articles')
    .select(FEED_ARTICLE_SELECT)
    .eq('status', 'published')
    .order('published_at', { ascending: false });

  if (options?.audience && options.audience !== 'all' && !isVirtualAudience(options.audience)) {
    query = query.eq('audience', options.audience);
  }

  const search = sanitizeSearchTerm(options?.search);
  if (search) {
    query = query.or(
      [`title.ilike.%${search}%`, `excerpt.ilike.%${search}%`, `content.ilike.%${search}%`].join(',')
    );
  }

  const { data, error } = await query;
  if (error) throw error;

  return (data || []) as ArticleSummaryRow[];
}

async function fetchArticleTags(articleIds: string[]): Promise<Record<string, string[]>> {
  if (articleIds.length === 0) return {};

  try {
    const { data, error } = await supabase
      .from('article_tags')
      .select('article_id, tags(name)')
      .in('article_id', articleIds);

    if (error) throw error;

    return buildTagMap(articleIds, (data || []) as unknown as ArticleTagLink[]);
  } catch {
    return Object.fromEntries(articleIds.map((id) => [id, []]));
  }
}

async function fetchArticleStats(articleIds: string[]): Promise<Record<string, ArticleStats>> {
  if (articleIds.length === 0) return {};

  try {
    const { data, error } = await supabase
      .from('article_stats')
      .select('article_id, view_count, likes')
      .in('article_id', articleIds);

    if (error) throw error;

    return buildStatsMap((data || []) as ArticleStatsRow[]);
  } catch {
    return {};
  }
}

function filterFeedRows(
  rows: ArticleSummaryRow[],
  tagMap: Record<string, string[]>,
  options?: Pick<FeedOptions, 'audience' | 'tag'>
): ArticleSummaryRow[] {
  const selectedTag = options?.tag ? normalizeTag(options.tag) : null;

  return rows.filter((row) => {
    const tags = tagMap[row.id] || [];
    if (!matchesAudience(options?.audience, row, tags)) return false;
    if (selectedTag && !tags.some((tag) => normalizeTag(tag) === selectedTag)) return false;
    return true;
  });
}

async function fetchFeedViaRpc(options?: FeedOptions): Promise<FeedListResponse> {
  const limit = clampLimit(options?.limit);
  const offset = clampOffset(options?.offset);
  const audience = options?.audience && options.audience !== 'all' ? options.audience : null;
  const search = sanitizeSearchTerm(options?.search) ?? null;
  const tag = options?.tag ?? null;

  const [{ data: rows, error: rowsError }, { data: tagCounts, error: tagError }] = await Promise.all([
    supabase.rpc(FEED_RPC_NAME, {
      feed_audience: audience,
      feed_tag: tag,
      feed_query: search,
      feed_limit: limit,
      feed_offset: offset,
    }),
    supabase.rpc(FEED_TAG_COUNTS_RPC_NAME, {
      feed_audience: audience,
      feed_query: search,
    }),
  ]);

  if (rowsError) throw rowsError;
  if (tagError) throw tagError;

  const feedRows = (rows || []) as FeedRpcRow[];
  const normalizedTagCounts = ((tagCounts || []) as Array<{ tag: string; count: number | null }>).map((entry) => ({
    tag: entry.tag,
    count: entry.count ?? 0,
  }));
  const total = feedRows[0]?.total_count ?? 0;

  return {
    items: feedRows.map(toFeedItemFromRpcRow),
    total,
    limit,
    offset,
    nextOffset: offset + limit < total ? offset + limit : null,
    tagCounts: normalizedTagCounts,
  };
}

async function getFeedFromQueries(options?: FeedOptions): Promise<FeedListResponse> {
  const limit = clampLimit(options?.limit);
  const offset = clampOffset(options?.offset);

  const rows = await fetchArticleSummaries(options);
  if (rows.length === 0) {
    return {
      items: [],
      total: 0,
      limit,
      offset,
      nextOffset: null,
      tagCounts: [],
    };
  }

  const articleIds = rows.map((row) => row.id);
  const tagMap = await fetchArticleTags(articleIds);
  const filteredRows = filterFeedRows(rows, tagMap, options);
  const tagCounts = buildTagCounts(
    filterFeedRows(rows, tagMap, { audience: options?.audience }),
    tagMap
  );
  const pageRows = filteredRows.slice(offset, offset + limit);
  const statsMap = await fetchArticleStats(pageRows.map((row) => row.id));

  return {
    items: pageRows.map((row) => toFeedItem(row, tagMap[row.id] || [], statsMap[row.id])),
    total: filteredRows.length,
    limit,
    offset,
    nextOffset: offset + limit < filteredRows.length ? offset + limit : null,
    tagCounts,
  };
}

async function fetchRelatedRowsByIds(articleIds: string[]): Promise<ArticleSummaryRow[]> {
  if (articleIds.length === 0) return [];

  const { data, error } = await supabase
    .from('articles')
    .select(FEED_ARTICLE_SELECT)
    .in('id', articleIds)
    .eq('status', 'published');

  if (error) throw error;
  return (data || []) as ArticleSummaryRow[];
}

async function fetchExplicitRelatedArticles(articleId: string): Promise<ArticleSummaryRow[]> {
  const { data, error } = await supabase
    .from('article_relations')
    .select('target_id, relation_type')
    .eq('source_id', articleId);

  if (error) throw error;

  const relationRows = (data || []) as Array<{ target_id: string; relation_type: string | null }>;
  if (relationRows.length === 0) return [];

  const relationPriority = new Map<string, number>([
    ['related', 0],
    ['general_version', 1],
    ['research_version', 1],
  ]);

  const articleRows = await fetchRelatedRowsByIds(relationRows.map((row) => row.target_id));
  const articleById = new Map(articleRows.map((row) => [row.id, row]));

  return relationRows
    .map((row) => ({
      row: articleById.get(row.target_id),
      priority: relationPriority.get(row.relation_type || 'related') ?? 2,
    }))
    .filter((entry): entry is { row: ArticleSummaryRow; priority: number } => Boolean(entry.row))
    .sort(
      (a, b) =>
        a.priority - b.priority ||
        b.row.published_at.localeCompare(a.row.published_at) ||
        a.row.title.localeCompare(b.row.title, 'zh-Hant')
    )
    .map((entry) => entry.row);
}

function toLinkedArticle(value: { id: string; slug: string; title: string }): LinkedArticle {
  return {
    article_id: value.id,
    slug: value.slug,
    title: value.title,
  };
}

async function fetchLegacyQuestionArticleLinks(questionIds: string[]): Promise<Record<string, LinkedArticle[]>> {
  const map: Record<string, LinkedArticle[]> = Object.fromEntries(questionIds.map((id) => [id, []]));

  const { data, error } = await supabase
    .from('articles')
    .select('id, slug, title, details')
    .eq('audience', 'member_qa');

  if (error) throw error;

  for (const article of (data || []) as Array<{ id: string; slug: string; title: string; details: JsonObject | null }>) {
    for (const questionId of extractQuestionIds(article.details)) {
      if (!map[questionId]) continue;
      map[questionId].push(toLinkedArticle(article));
    }
  }

  return Object.fromEntries(
    Object.entries(map).map(([questionId, links]) => [questionId, normalizeLinkedArticles(links)])
  );
}

async function fetchQuestionArticleLinks(questionIds: string[]): Promise<Record<string, LinkedArticle[]>> {
  const map: Record<string, LinkedArticle[]> = Object.fromEntries(questionIds.map((id) => [id, []]));
  if (questionIds.length === 0) return map;

  try {
    const { data, error } = await supabase
      .from('question_articles')
      .select('question_id, article_id, article:articles(id, slug, title)')
      .in('question_id', questionIds);

    if (error) throw error;

    for (const row of (data || []) as QuestionArticleJoinRow[]) {
      const article = Array.isArray(row.article) ? row.article[0] : row.article;
      if (!article) continue;
      map[row.question_id].push(toLinkedArticle(article));
    }
  } catch (error) {
    if (!isMissingCapabilityError(error)) {
      console.warn('Question article join fallback:', error);
    }
  }

  const unresolvedIds = questionIds.filter((questionId) => (map[questionId] || []).length === 0);
  if (unresolvedIds.length === 0) {
    return Object.fromEntries(
      Object.entries(map).map(([questionId, links]) => [questionId, normalizeLinkedArticles(links)])
    );
  }

  try {
    const legacyMap = await fetchLegacyQuestionArticleLinks(unresolvedIds);
    for (const questionId of unresolvedIds) {
      map[questionId] = normalizeLinkedArticles([...(map[questionId] || []), ...(legacyMap[questionId] || [])]);
    }
  } catch {
    // Ignore legacy lookup failures so questions can still render.
  }

  return map;
}

function toQuestionItem(row: QuestionRow, linkedArticles: LinkedArticle[]): QuestionItem {
  return {
    id: row.id,
    timestamp: row.created_at ?? undefined,
    created_at: row.created_at ?? undefined,
    answered_at: row.answered_at ?? undefined,
    user_id: row.user_id ?? undefined,
    question: row.question,
    priority: row.priority ?? 'medium',
    status: row.status ?? 'open',
    answer: row.answer ?? undefined,
    proposer: row.proposer ?? undefined,
    score: row.score ?? undefined,
    current_rank: row.current_rank ?? undefined,
    score_breakdown: row.score_breakdown ?? undefined,
    prev_rank: row.prev_rank ?? undefined,
    linked_articles: linkedArticles,
    feed_articles: linkedArticles.map((article) => article.slug),
  };
}

async function readFirstJsonValue<T>(candidates: string[]): Promise<T | null> {
  for (const candidate of candidates) {
    try {
      const content = await fs.readFile(candidate, 'utf8');
      return JSON.parse(content) as T;
    } catch {
      // Try the next candidate path.
    }
  }

  return null;
}

async function readFirstJsonArray<T>(candidates: string[]): Promise<T[]> {
  const parsed = await readFirstJsonValue<unknown>(candidates);
  return Array.isArray(parsed) ? (parsed as T[]) : [];
}

function getQuestionFallbackPaths(source?: string): string[] {
  if (source === 'internal') {
    return [
      path.resolve(process.cwd(), '..', 'storage', 'memory', 'open_questions.json'),
      path.resolve(process.cwd(), 'data', 'open_questions.json'),
      path.resolve(process.cwd(), 'public', 'data', 'open_questions.json'),
    ];
  }

  if (source === 'user') {
    return [
      path.resolve(process.cwd(), '..', 'storage', 'mock_user_questions.json'),
      path.resolve(process.cwd(), 'data', 'mock_user_questions.json'),
      path.resolve(process.cwd(), 'public', 'data', 'mock_user_questions.json'),
    ];
  }

  return [];
}

async function getQuestionsFromLocalFallback(source?: string): Promise<QuestionItem[]> {
  const rows = await readFirstJsonArray<LocalQuestionRow>(getQuestionFallbackPaths(source));
  if (rows.length === 0) return [];

  const articleIdentifiers = rows.flatMap((row) =>
    Array.isArray(row.feed_articles) ? row.feed_articles.filter((value): value is string => typeof value === 'string') : []
  );

  let articleLookup: Record<string, LinkedArticle> = {};
  if (articleIdentifiers.length > 0) {
    try {
      articleLookup = await fetchArticleLinksByIdentifiers(articleIdentifiers);
    } catch {
      articleLookup = {};
    }
  }

  return rows
    .filter((row): row is LocalQuestionRow & { question: string } => typeof row.question === 'string' && row.question.trim().length > 0)
    .map((row, index) => {
      const feedArticles = Array.isArray(row.feed_articles)
        ? row.feed_articles.filter((value): value is string => typeof value === 'string')
        : [];
      const linkedArticles = normalizeLinkedArticles(
        feedArticles
          .map((identifier) => articleLookup[identifier])
          .filter((article): article is LinkedArticle => Boolean(article))
      );

      return {
        id: row.id ?? `${source ?? 'question'}_${index}`,
        timestamp: row.timestamp ?? row.created_at ?? undefined,
        created_at: row.created_at ?? row.timestamp ?? undefined,
        answered_at: row.answered_at ?? undefined,
        user_id: row.user_id ?? undefined,
        question: row.question,
        priority: row.priority ?? 'medium',
        status: row.status ?? 'open',
        answer: row.answer ?? undefined,
        proposer: row.proposer ?? undefined,
        score: typeof row.score === 'number' ? row.score : undefined,
        current_rank: typeof row.current_rank === 'number' ? row.current_rank : undefined,
        score_breakdown: row.score_breakdown ?? undefined,
        prev_rank: typeof row.prev_rank === 'number' ? row.prev_rank : undefined,
        feed_articles: feedArticles,
        linked_articles: linkedArticles,
      } satisfies QuestionItem;
    })
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
}

function buildLocalFeedEntry(item: LocalFeedRow): LocalFeedEntry | null {
  const slug = typeof item.id === 'string' ? item.id.trim() : '';
  const title = typeof item.title === 'string' ? item.title.trim() : '';
  const publishedAt = typeof item.published_at === 'string' ? item.published_at : '';
  const status = typeof item.status === 'string' ? item.status : 'published';

  if (!slug || !title || !publishedAt || status !== 'published') return null;

  const tags = parseTags(Array.isArray(item.tags) ? item.tags.filter((tag): tag is string => typeof tag === 'string') : []);
  const article: ArticleSummaryRow = {
    id: slug,
    slug,
    title,
    excerpt: buildExcerpt(item.description),
    audience: resolveLocalAudience(item),
    phase: typeof item.phase === 'string' ? item.phase : null,
    status,
    category: typeof item.category === 'string' ? item.category : 'milestone',
    proposer: extractProposerFromText(item.description),
    published_at: publishedAt,
    created_at: typeof item.created_at === 'string' ? item.created_at : null,
    details: isJsonObject(item.details) ? item.details : null,
  };

  const searchText = [
    article.title,
    article.excerpt ?? '',
    typeof item.description === 'string' ? item.description : '',
    article.details ? JSON.stringify(article.details) : '',
    tags.join(' '),
  ]
    .join('\n')
    .toLowerCase();

  return { article, tags, searchText };
}

async function getLocalFeedEntries(): Promise<LocalFeedEntry[] | null> {
  const rows = await readFirstJsonValue<unknown>(getFeedSnapshotPaths());
  if (!Array.isArray(rows)) return null;

  return (rows as LocalFeedRow[])
    .map(buildLocalFeedEntry)
    .filter((entry): entry is LocalFeedEntry => Boolean(entry))
    .sort((a, b) => b.article.published_at.localeCompare(a.article.published_at));
}

function matchesSearchText(searchText: string, search?: string): boolean {
  const normalized = sanitizeSearchTerm(search);
  if (!normalized) return true;
  return normalized
    .toLowerCase()
    .split(' ')
    .filter(Boolean)
    .every((term) => searchText.includes(term));
}

async function getFeedFromLocalSnapshot(options?: FeedOptions): Promise<FeedListResponse | null> {
  const limit = clampLimit(options?.limit);
  const offset = clampOffset(options?.offset);
  const entries = await getLocalFeedEntries();
  if (!entries) return null;

  const audienceAndSearchEntries = entries.filter(
    ({ article, tags, searchText }) =>
      matchesAudience(options?.audience, article, tags) && matchesSearchText(searchText, options?.search)
  );

  const selectedTag = options?.tag ? normalizeTag(options.tag) : null;
  const filteredEntries = audienceAndSearchEntries.filter(
    ({ tags }) => !selectedTag || tags.some((tag) => normalizeTag(tag) === selectedTag)
  );

  const tagMap = Object.fromEntries(
    audienceAndSearchEntries.map(({ article, tags }) => [article.id, tags])
  ) as Record<string, string[]>;
  const pageEntries = filteredEntries.slice(offset, offset + limit);

  return {
    items: pageEntries.map(({ article, tags }) => toFeedItem(article, tags)),
    total: filteredEntries.length,
    limit,
    offset,
    nextOffset: offset + limit < filteredEntries.length ? offset + limit : null,
    tagCounts: buildTagCounts(
      audienceAndSearchEntries.map(({ article }) => article),
      tagMap
    ),
  };
}

function calcMetrics(entries: PaperTradeRow[]): StrategyMetrics | null {
  const returns = extractRealizedStrategyReturns(entries.map((entry) => entry.entry));

  if (returns.length < 10) return null;

  const n = returns.length;
  const years = n / 252;

  let cumulative = 1.0;
  let peak = 1.0;
  let maxDrawdown = 0;
  let currentDrawdownStart = 0;
  let maxDrawdownDays = 0;

  for (let i = 0; i < returns.length; i += 1) {
    cumulative *= 1 + returns[i];
    if (cumulative > peak) {
      peak = cumulative;
      currentDrawdownStart = i;
    }
    const drawdown = (cumulative - peak) / peak;
    if (drawdown < maxDrawdown) {
      maxDrawdown = drawdown;
      maxDrawdownDays = i - currentDrawdownStart;
    }
  }

  const cumulativeReturn = (cumulative - 1) * 100;
  const annualizedReturn = years > 0 ? (Math.pow(cumulative, 1 / years) - 1) * 100 : 0;
  const meanReturn = returns.reduce((sum, value) => sum + value, 0) / n;
  const variance = returns.reduce((sum, value) => sum + (value - meanReturn) ** 2, 0) / (n - 1);
  const dailyVolatility = Math.sqrt(Math.max(variance, 0));
  const annualizedVolatility = dailyVolatility * Math.sqrt(252) * 100;
  const sharpe = dailyVolatility > 0 ? (meanReturn / dailyVolatility) * Math.sqrt(252) : 0;

  const negativeReturns = returns.filter((value) => value < 0);
  const downsideDeviation =
    negativeReturns.length > 0
      ? Math.sqrt(negativeReturns.reduce((sum, value) => sum + value * value, 0) / negativeReturns.length)
      : dailyVolatility;
  const sortino = downsideDeviation > 0 ? (meanReturn / downsideDeviation) * Math.sqrt(252) : sharpe;
  const calmar = maxDrawdown !== 0 ? annualizedReturn / Math.abs(maxDrawdown * 100) : 0;
  const winRate = (returns.filter((value) => value > 0).length / n) * 100;

  const sortedReturns = [...returns].sort((a, b) => a - b);
  const varIndex = Math.floor(n * 0.05);
  const var95 = varIndex < n ? sortedReturns[varIndex] * 100 : 0;
  const cvar95 =
    varIndex > 0
      ? (sortedReturns.slice(0, varIndex + 1).reduce((sum, value) => sum + value, 0) / (varIndex + 1)) * 100
      : var95;

  return {
    display_name: '',
    cumulative_return: +cumulativeReturn.toFixed(2),
    annualized_return: +annualizedReturn.toFixed(2),
    sharpe: +sharpe.toFixed(2),
    sortino: +sortino.toFixed(2),
    max_drawdown: +(maxDrawdown * 100).toFixed(2),
    annualized_vol: +annualizedVolatility.toFixed(2),
    calmar: +calmar.toFixed(2),
    win_rate: +winRate.toFixed(1),
    var_95: +var95.toFixed(2),
    cvar_95: +cvar95.toFixed(2),
    max_drawdown_days: maxDrawdownDays,
    best_day: +(Math.max(...returns) * 100).toFixed(2),
    worst_day: +(Math.min(...returns) * 100).toFixed(2),
    trading_days: n,
  };
}

function buildSparkline(entries: PaperTradeRow[]): number[] {
  const series = buildStrategyPerformanceSeries(entries.map((row) => row.entry), 1_000_000);
  return compressStrategyValues(
    series.map((point) => point.value),
    60
  );
}

async function fetchPaperTradeRows(): Promise<PaperTradeRow[]> {
  let allRows: PaperTradeRow[] = [];
  let from = 0;
  const pageSize = 1000;

  while (true) {
    const { data, error } = await supabase
      .from('paper_trades')
      .select('strategy, entry, trade_date')
      .gte('trade_date', COMMON_START)
      .order('trade_date', { ascending: true })
      .range(from, from + pageSize - 1);

    if (error) throw error;
    const page = (data || []) as PaperTradeRow[];
    if (page.length === 0) break;
    allRows = allRows.concat(page);
    if (page.length < pageSize) break;
    from += pageSize;
  }

  return allRows;
}

function groupPaperTrades(rows: PaperTradeRow[]): Record<string, { entries: PaperTradeEntry[]; initial_capital: number }> {
  const grouped: Record<string, { entries: PaperTradeEntry[]; initial_capital: number }> = {};
  for (const row of rows) {
    if (!grouped[row.strategy]) {
      grouped[row.strategy] = { entries: [], initial_capital: 1_000_000 };
    }
    if (row.entry) grouped[row.strategy].entries.push(row.entry);
  }
  return grouped;
}

function normalizePaperTradeWeights(value: JsonValue | undefined): Record<string, number> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};

  return Object.fromEntries(
    Object.entries(value)
      .map(([key, rawValue]) => [key, typeof rawValue === 'number' ? rawValue : Number(rawValue)])
      .filter(([, numericValue]) => Number.isFinite(numericValue))
  );
}

function getAssetColumnsForPaperTrades(entries: PaperTradeEntry[]): string[] {
  const assetSet = new Set<string>();

  for (const entry of entries) {
    const weights = normalizePaperTradeWeights(entry.weights);
    for (const asset of Object.keys(weights)) {
      assetSet.add(asset);
    }
  }

  if (assetSet.size === 0) return ['SPY'];
  return Array.from(assetSet).sort();
}

function getLatestAllocation(entries: PaperTradeEntry[]): { weights: Record<string, number>; cashWeight: number } {
  const latest = entries.at(-1);
  if (!latest) {
    return { weights: {}, cashWeight: 1 };
  }

  const weights = normalizePaperTradeWeights(latest.weights);
  const normalizedWeights =
    Object.keys(weights).length > 0
      ? weights
      : typeof latest.recommended_weight === 'number'
        ? { SPY: latest.recommended_weight }
        : {};

  const grossWeight = Object.values(normalizedWeights).reduce((sum, value) => sum + value, 0);
  const explicitCashWeight = typeof latest.cash_weight === 'number' ? latest.cash_weight : null;

  return {
    weights: normalizedWeights,
    cashWeight: explicitCashWeight ?? Math.max(0, 1 - grossWeight),
  };
}

function buildPaperTradingStrategy(entries: PaperTradeEntry[], initialCapital = 1_000_000): PaperTradingStrategy {
  const chartData = buildStrategyPerformanceSeries(entries, initialCapital);
  const latestValue = chartData.length > 0 ? chartData[chartData.length - 1].value : initialCapital;
  const totalReturnPct = +(((latestValue - initialCapital) / initialCapital) * 100).toFixed(2);
  const realizedReturns = extractRealizedStrategyReturns(entries);
  const winRate =
    realizedReturns.length > 0
      ? +((realizedReturns.filter((value) => value > 0).length / realizedReturns.length) * 100).toFixed(1)
      : 0;
  const latestAllocation = getLatestAllocation(entries);

  return {
    initial_capital: initialCapital,
    entries,
    chart_data: chartData,
    asset_columns: getAssetColumnsForPaperTrades(entries),
    latest_value: latestValue,
    total_return_pct: totalReturnPct,
    win_rate: winRate,
    latest_weights: latestAllocation.weights,
    latest_cash_weight: latestAllocation.cashWeight,
    trading_days: entries.length,
  };
}

function buildPaperTradesPayload(rows: PaperTradeRow[]): PaperTradingMap {
  const grouped = groupPaperTrades(rows);
  return Object.fromEntries(
    Object.entries(grouped).map(([strategy, value]) => [
      strategy,
      buildPaperTradingStrategy(value.entries, value.initial_capital),
    ])
  );
}

function buildPaperTradesPayloadFromLocalSnapshot(
  snapshot: Record<string, LocalPaperTradingSnapshotEntry>
): PaperTradingMap {
  return Object.fromEntries(
    Object.entries(snapshot).flatMap(([strategy, rawValue]) => {
      if (!isJsonObject(rawValue)) return [];

      const entries = Array.isArray(rawValue.entries)
        ? rawValue.entries.filter((entry): entry is PaperTradeEntry => isJsonObject(entry))
        : [];
      const initialCapital = typeof rawValue.initial_capital === 'number' ? rawValue.initial_capital : 1_000_000;
      const strategyPayload = buildPaperTradingStrategy(entries, initialCapital);
      const stats = isJsonObject(rawValue.stats) ? rawValue.stats : null;
      if (stats && typeof stats.display_name === 'string') {
        strategyPayload.name = stats.display_name;
      }

      return [[strategy, strategyPayload] as const];
    })
  );
}

function normalizeTradeDate(entry: PaperTradeEntry): string | null {
  const value = entry.trade_date ?? entry.data_date ?? entry.date ?? entry.prediction_date;
  if (typeof value !== 'string' || value.trim().length < 10) return null;
  return value.slice(0, 10);
}

function chunkArray<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function isSyncPaperTradingStrategy(value: SyncPaperTradingStrategy | null | undefined): value is SyncPaperTradingStrategy {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

async function computeStrategyMetricsPayload(): Promise<Record<string, StrategyMetricsCachePayload>> {
  const rows = await fetchPaperTradeRows();
  const grouped = new Map<string, PaperTradeRow[]>();

  for (const row of rows) {
    if (!grouped.has(row.strategy)) grouped.set(row.strategy, []);
    grouped.get(row.strategy)?.push(row);
  }

  const payload: Record<string, StrategyMetricsCachePayload> = {};

  for (const [strategy, entries] of grouped.entries()) {
    const metrics = calcMetrics(entries);
    if (!metrics) continue;

    payload[strategy] = {
      display_name: strategy,
      metrics: {
        ...metrics,
        display_name: strategy,
        cache_version: STRATEGY_METRICS_CACHE_VERSION,
      },
      sparkline: buildSparkline(entries),
      latest_trade_date: entries[entries.length - 1]?.trade_date ?? null,
      updated_at: new Date().toISOString(),
    };
  }

  return payload;
}

async function readLocalPaperTradingSnapshot(): Promise<Record<string, LocalPaperTradingSnapshotEntry> | null> {
  const snapshot = await readFirstJsonValue<unknown>(getPaperTradingSnapshotPaths());
  return isJsonObject(snapshot) ? (snapshot as Record<string, LocalPaperTradingSnapshotEntry>) : null;
}

async function readLocalPaperTradingPayload(): Promise<PaperTradingMap | null> {
  const snapshot = await readLocalPaperTradingSnapshot();
  if (!snapshot) return null;

  const payload = buildPaperTradesPayloadFromLocalSnapshot(snapshot);
  return Object.keys(payload).length > 0 ? payload : null;
}

async function readLocalStrategyArticlesMap(): Promise<Record<string, LinkedArticle[]>> {
  const snapshot = await readFirstJsonValue<unknown>(getStrategyArticlesSnapshotPaths());
  if (!isJsonObject(snapshot)) return {};

  return Object.fromEntries(
    Object.entries(snapshot).map(([strategyKey, rawArticles]) => {
      if (!Array.isArray(rawArticles)) return [strategyKey, []];

      const links = rawArticles
        .map((article) => {
          if (!isJsonObject(article)) return null;
          const slug =
            typeof article.slug === 'string'
              ? article.slug
              : typeof article.id === 'string'
                ? article.id
                : null;
          const articleId =
            typeof article.article_id === 'string'
              ? article.article_id
              : typeof article.id === 'string'
                ? article.id
                : slug;
          const title = typeof article.title === 'string' ? article.title : slug;

          return slug && articleId && title
            ? ({
                article_id: articleId,
                slug,
                title,
              } satisfies LinkedArticle)
            : null;
        })
        .filter((article): article is LinkedArticle => Boolean(article));

      return [strategyKey, normalizeLinkedArticles(links)];
    })
  );
}

async function readLocalStrategyMetricsPayload(): Promise<Record<string, StrategyMetricsCachePayload> | null> {
  const [metricsSnapshot, paperTradingMap] = await Promise.all([
    readFirstJsonValue<unknown>(getStrategyMetricsSnapshotPaths()),
    readLocalPaperTradingPayload(),
  ]);

  if (!isJsonObject(metricsSnapshot)) return null;

  const payload = Object.fromEntries(
    Object.entries(metricsSnapshot).flatMap(([strategyKey, rawValue]) => {
      if (!isJsonObject(rawValue)) return [];

      const displayName =
        typeof rawValue.display_name === 'string'
          ? rawValue.display_name
          : paperTradingMap?.[strategyKey]?.name || strategyKey;
      const chartValues = paperTradingMap?.[strategyKey]?.chart_data.map((point) => point.value) ?? [];
      const latestTradeDate =
        paperTradingMap?.[strategyKey]?.entries
          .map((entry) => normalizeTradeDate(entry))
          .filter((value): value is string => Boolean(value))
          .at(-1) ?? null;

      const metrics = {
        ...(rawValue as unknown as StrategyMetrics),
        display_name: displayName,
        cache_version: STRATEGY_METRICS_CACHE_VERSION,
      };

      return [[
        strategyKey,
        {
          display_name: displayName,
          metrics,
          sparkline: chartValues.length > 0 ? compressStrategyValues(chartValues, 60) : [],
          latest_trade_date: latestTradeDate,
          updated_at: latestTradeDate,
        } satisfies StrategyMetricsCachePayload,
      ] as const];
    })
  );

  return Object.keys(payload).length > 0 ? payload : null;
}

async function readLocalStrategyMarketSnapshot(): Promise<LocalStrategyMarketSnapshot | null> {
  const rawFeed = await readFirstJsonValue<unknown>(getFeedSnapshotPaths());
  const latestStrategyRow = Array.isArray(rawFeed)
    ? (rawFeed as LocalFeedRow[])
        .filter(
          (item) =>
            item.status === 'published' &&
            isJsonObject(item.details) &&
            isJsonObject(item.details.strategies)
        )
        .sort((a, b) => (b.published_at ?? '').localeCompare(a.published_at ?? ''))
        .at(0)
    : null;

  const paperTradingSnapshot = await readLocalPaperTradingSnapshot();
  const latestPaperTradeEntries = paperTradingSnapshot
    ? Object.values(paperTradingSnapshot)
        .flatMap((entry) => (Array.isArray(entry.entries) ? entry.entries.filter((item): item is PaperTradeEntry => isJsonObject(item)) : []))
        .sort((a, b) => (normalizeTradeDate(b) ?? '').localeCompare(normalizeTradeDate(a) ?? ''))
    : [];
  const latestPaperTrade = latestPaperTradeEntries[0] ?? null;

  const details = latestStrategyRow && isJsonObject(latestStrategyRow.details) ? latestStrategyRow.details : null;
  const rawStrategies = details && isJsonObject(details.strategies) ? details.strategies : {};
  const strategyWeights = Object.fromEntries(
    Object.entries(rawStrategies).flatMap(([strategyKey, rawWeights]) => {
      const weights = normalizeStrategyWeightsForDisplay(rawWeights);
      return Object.keys(weights).length > 0 ? [[strategyKey, weights] as const] : [];
    })
  );

  if (!details && !latestPaperTrade) return null;

  return {
    updated_at:
      latestStrategyRow?.published_at ??
      (latestPaperTrade ? normalizeTradeDate(latestPaperTrade) : null) ??
      null,
    sigma_ann:
      toNumber(details?.sigma_annual) ??
      toNumber(details?.sigma_ann) ??
      toNumber(latestPaperTrade?.sigma_spy_ann),
    vix_level: toNumber(details?.vix_level),
    spy_close: toNumber(details?.spy_close) ?? toNumber(latestPaperTrade?.spy_close),
    gld_close: toNumber(details?.gld_close) ?? toNumber(latestPaperTrade?.gld_close),
    tw50_close:
      toNumber(details?.tw50_close) ??
      toNumber(details?.['0050_close']) ??
      toNumber(latestPaperTrade?.tw50_close) ??
      toNumber(latestPaperTrade?.['0050_close']),
    strategy_weights: strategyWeights,
  };
}

async function readStrategyMetricsCacheTable(): Promise<Record<string, StrategyMetricsCachePayload>> {
  try {
    const { data, error } = await supabase
      .from('strategy_metrics_cache')
      .select('strategy, display_name, metrics, sparkline, latest_trade_date, updated_at');

    if (error) throw error;

    const map: Record<string, StrategyMetricsCachePayload> = {};
    for (const row of (data || []) as StrategyMetricsCacheRow[]) {
      if (!isJsonObject(row.metrics)) continue;
      const cacheVersion = typeof row.metrics.cache_version === 'number' ? row.metrics.cache_version : null;
      if (cacheVersion !== STRATEGY_METRICS_CACHE_VERSION) continue;
      map[row.strategy] = {
        display_name: row.display_name,
        metrics: row.metrics as unknown as StrategyMetrics,
        sparkline: Array.isArray(row.sparkline)
          ? row.sparkline.filter((value): value is number => typeof value === 'number')
          : [],
        latest_trade_date: row.latest_trade_date,
        updated_at: row.updated_at,
      };
    }
    return map;
  } catch (error) {
    if (!isMissingCapabilityError(error)) {
      console.warn('Strategy metrics cache read fallback:', error);
    }
    return {};
  }
}

async function persistStrategyMetricsCache(payload: Record<string, StrategyMetricsCachePayload>): Promise<void> {
  const rows = Object.entries(payload).map(([strategy, value]) => ({
    strategy,
    display_name: value.display_name,
    metrics: value.metrics,
    sparkline: value.sparkline,
    latest_trade_date: value.latest_trade_date,
    updated_at: value.updated_at ?? new Date().toISOString(),
  }));

  if (rows.length === 0) return;

  try {
    const { error } = await supabase
      .from('strategy_metrics_cache')
      .upsert(rows, { onConflict: 'strategy' });

    if (error) throw error;
  } catch (error) {
    if (!isMissingCapabilityError(error)) {
      console.warn('Strategy metrics cache write fallback:', error);
    }
  }
}

async function loadStrategyMetricsPayload(forceFresh = false): Promise<Record<string, StrategyMetricsCachePayload>> {
  if (!forceFresh) {
    const localSnapshot = await readLocalStrategyMetricsPayload();
    if (localSnapshot && Object.keys(localSnapshot).length > 0) return localSnapshot;
  }

  if (!forceFresh) {
    const cachedRows = await readStrategyMetricsCacheTable();
    if (Object.keys(cachedRows).length > 0) return cachedRows;
  }

  const computed = await computeStrategyMetricsPayload();
  await persistStrategyMetricsCache(computed);
  return computed;
}

async function loadStrategySignalRows(): Promise<StrategySignalRow[]> {
  const { data, error } = await supabase
    .from('strategy_signals')
    .select('*')
    .eq('is_active', true)
    .order('display_order', { ascending: true });

  if (error) throw error;
  return (data || []) as StrategySignalRow[];
}

async function getStrategySignalsFromLocalSnapshot(): Promise<StrategySignal[] | null> {
  const [marketSnapshot, metricsPayload, articleMap, paperTradingMap] = await Promise.all([
    readLocalStrategyMarketSnapshot(),
    readLocalStrategyMetricsPayload(),
    readLocalStrategyArticlesMap(),
    readLocalPaperTradingPayload(),
  ]);

  const strategyKeys = Array.from(
    new Set([
      ...Object.keys(marketSnapshot?.strategy_weights ?? {}),
      ...Object.keys(metricsPayload ?? {}),
      ...Object.keys(articleMap),
      ...Object.keys(paperTradingMap ?? {}),
    ])
  );

  if (strategyKeys.length === 0) return null;

  return strategyKeys.map((strategyKey, index) => {
    const weights =
      marketSnapshot?.strategy_weights[strategyKey] ??
      normalizeStrategyWeightsForDisplay(paperTradingMap?.[strategyKey]?.latest_weights ?? {});
    const metadata = LOCAL_STRATEGY_METADATA[strategyKey];
    const displayName =
      metricsPayload?.[strategyKey]?.display_name ??
      paperTradingMap?.[strategyKey]?.name ??
      strategyKey;
    const latestTradeDate =
      paperTradingMap?.[strategyKey]?.entries
        .map((entry) => normalizeTradeDate(entry))
        .filter((value): value is string => Boolean(value))
        .at(-1) ?? null;

    return {
      id: index + 1,
      strategy_name: displayName,
      strategy_key: strategyKey,
      description: undefined,
      howto: metadata?.howto ?? '',
      color: metadata?.color ?? DEFAULT_STRATEGY_COLOR,
      weights,
      vix_level: marketSnapshot?.vix_level ?? null,
      sigma_ann: marketSnapshot?.sigma_ann ?? null,
      updated_at: marketSnapshot?.updated_at ?? latestTradeDate ?? new Date().toISOString(),
      is_active: true,
      articles: (articleMap[strategyKey] || []).map((article) => article.slug),
      article_links: articleMap[strategyKey] || [],
    } satisfies StrategySignal;
  });
}

function isUuidLike(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

async function fetchArticleLinksByIdentifiers(identifiers: string[]): Promise<Record<string, LinkedArticle>> {
  const lookup: Record<string, LinkedArticle> = {};
  const unique = Array.from(new Set(identifiers.map((identifier) => identifier.trim()).filter(Boolean)));

  if (unique.length === 0) return lookup;

  const { data: slugMatches, error: slugError } = await supabase
    .from('articles')
    .select('id, slug, title')
    .in('slug', unique)
    .eq('status', 'published');

  if (slugError) throw slugError;

  for (const article of (slugMatches || []) as Array<{ id: string; slug: string; title: string }>) {
    lookup[article.slug] = toLinkedArticle(article);
  }

  const unresolved = unique.filter((identifier) => !lookup[identifier] && isUuidLike(identifier));
  if (unresolved.length === 0) return lookup;

  const { data: idMatches, error: idError } = await supabase
    .from('articles')
    .select('id, slug, title')
    .in('id', unresolved)
    .eq('status', 'published');

  if (idError) throw idError;

  for (const article of (idMatches || []) as Array<{ id: string; slug: string; title: string }>) {
    lookup[article.id] = toLinkedArticle(article);
  }

  return lookup;
}

function normalizeStrategySignal(row: StrategySignalRow, articleLookup: Record<string, LinkedArticle>): StrategySignal {
  const articleRefs = Array.isArray(row.articles)
    ? row.articles.map(extractArticleIdentifier).filter((value): value is string => Boolean(value))
    : [];

  return {
    id: row.id,
    strategy_name: row.strategy_name,
    strategy_key: row.strategy_key,
    description: row.description ?? undefined,
    howto: row.howto ?? '',
    color: row.color ?? '#6B7280',
    weights: normalizeWeights(row.weights),
    vix_level: row.vix_level ?? null,
    sigma_ann: row.sigma_ann ?? null,
    updated_at: row.updated_at,
    is_active: row.is_active,
    articles: articleRefs,
    article_links: normalizeLinkedArticles(
      articleRefs
        .map((identifier) => articleLookup[identifier])
        .filter((article): article is LinkedArticle => Boolean(article))
    ),
  };
}

function normalizeRiskForecastPayload(rawPayload: unknown, generatedAt?: string | null): RiskForecast {
  const payload = isJsonObject(rawPayload) ? rawPayload : {};
  const rawAssets = isJsonObject(payload.assets) ? payload.assets : {};
  const normalizedAssets = Object.fromEntries(
    Object.entries(rawAssets).map(([ticker, rawAsset]) => {
      if (!isJsonObject(rawAsset)) return [ticker, rawAsset];

      const rawArticles = Array.isArray(rawAsset.articles) ? rawAsset.articles : [];
      const normalizedArticles = rawArticles
        .map((article) => {
          if (!isJsonObject(article)) return null;
          const slug = typeof article.slug === 'string' ? article.slug : typeof article.id === 'string' ? article.id : null;
          const articleId =
            typeof article.article_id === 'string'
              ? article.article_id
              : typeof article.id === 'string'
                ? article.id
                : slug;
          const title = typeof article.title === 'string' ? article.title : slug;

          return slug && articleId && title
            ? ({
                article_id: articleId,
                slug,
                title,
              } satisfies LinkedArticle)
            : null;
        })
        .filter((article): article is LinkedArticle => Boolean(article));

      return [
        ticker,
        {
          ...rawAsset,
          articles: normalizedArticles,
          model_note: typeof rawAsset.model_note === 'string' ? rawAsset.model_note : undefined,
        },
      ];
    })
  );

  return {
    generated_at:
      generatedAt ||
      (typeof payload.generated_at === 'string' ? payload.generated_at : new Date().toISOString()),
    model: typeof payload.model === 'string' ? payload.model : '',
    assets: (normalizedAssets as unknown) as RiskForecast['assets'],
  };
}

async function buildStrategyOverview(): Promise<StrategyOverview> {
  const [signals, metricsPayload, recentPaperTrades] = await Promise.all([
    getStrategySignals(),
    getCachedStrategyMetricsPayload(),
    supabase
      .from('paper_trades')
      .select('trade_date, entry')
      .order('trade_date', { ascending: false })
      .limit(60),
  ]);

  const latestEntries = (recentPaperTrades.data || []) as Array<{ trade_date: string; entry: PaperTradeEntry | null }>;
  let spyClose: number | null = null;
  let gldClose: number | null = null;
  let tw50Close: number | null = null;

  for (const row of latestEntries) {
    const entry = row.entry;
    if (!entry) continue;
    if (spyClose == null) spyClose = toNumber(entry.spy_close);
    if (gldClose == null) gldClose = toNumber(entry.gld_close);
    if (tw50Close == null) {
      tw50Close = toNumber(entry.tw50_close) ?? toNumber(entry['0050_close']);
    }
    if (spyClose != null && gldClose != null && tw50Close != null) break;
  }

  const sortedStrategies = [...signals].sort((a, b) => {
    const sharpeA = metricsPayload[a.strategy_key]?.metrics.sharpe ?? -Infinity;
    const sharpeB = metricsPayload[b.strategy_key]?.metrics.sharpe ?? -Infinity;
    return sharpeB - sharpeA || a.strategy_name.localeCompare(b.strategy_name, 'zh-Hant');
  });

  const signalUpdatedAt =
    sortedStrategies
      .map((strategy) => strategy.updated_at)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null;

  const metricsUpdatedAt =
    Object.values(metricsPayload)
      .map((value) => value.updated_at)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null;

  const updatedAt = [signalUpdatedAt, metricsUpdatedAt]
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? null;

  return {
    updated_at: updatedAt,
    market: {
      sigma_ann: sortedStrategies[0]?.sigma_ann ?? null,
      vix_level: sortedStrategies[0]?.vix_level ?? null,
      spy_close: spyClose,
      gld_close: gldClose,
      tw50_close: tw50Close,
    },
    strategies: sortedStrategies.map((signal) => ({
      id: signal.id,
      strategy_key: signal.strategy_key,
      strategy_name: signal.strategy_name,
      howto: signal.howto,
      color: signal.color,
      weights: signal.weights,
      metrics: metricsPayload[signal.strategy_key]?.metrics,
      sparkline: metricsPayload[signal.strategy_key]?.sparkline ?? [],
      article_links: signal.article_links ?? [],
    })),
  };
}

async function getStrategyOverviewFromLocalSnapshot(): Promise<StrategyOverview | null> {
  const [signals, metricsPayload, marketSnapshot] = await Promise.all([
    getStrategySignalsFromLocalSnapshot(),
    readLocalStrategyMetricsPayload(),
    readLocalStrategyMarketSnapshot(),
  ]);

  if (!signals || signals.length === 0) return null;

  const sortedStrategies = [...signals].sort((a, b) => {
    const sharpeA = metricsPayload?.[a.strategy_key]?.metrics.sharpe ?? -Infinity;
    const sharpeB = metricsPayload?.[b.strategy_key]?.metrics.sharpe ?? -Infinity;
    return sharpeB - sharpeA || a.strategy_name.localeCompare(b.strategy_name, 'zh-Hant');
  });

  const updatedAt =
    [
      marketSnapshot?.updated_at ?? null,
      ...sortedStrategies.map((strategy) => strategy.updated_at),
      ...Object.values(metricsPayload ?? {}).map((value) => value.updated_at),
    ]
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null;

  return {
    updated_at: updatedAt,
    market: {
      sigma_ann: marketSnapshot?.sigma_ann ?? sortedStrategies[0]?.sigma_ann ?? null,
      vix_level: marketSnapshot?.vix_level ?? sortedStrategies[0]?.vix_level ?? null,
      spy_close: marketSnapshot?.spy_close ?? null,
      gld_close: marketSnapshot?.gld_close ?? null,
      tw50_close: marketSnapshot?.tw50_close ?? null,
    },
    strategies: sortedStrategies.map((signal, index) => ({
      id: signal.id ?? index + 1,
      strategy_key: signal.strategy_key,
      strategy_name: signal.strategy_name,
      howto: signal.howto,
      color: signal.color,
      weights: signal.weights,
      metrics: metricsPayload?.[signal.strategy_key]?.metrics,
      sparkline: metricsPayload?.[signal.strategy_key]?.sparkline ?? [],
      article_links: signal.article_links || [],
    })),
  };
}

async function fetchLatestRiskForecast(): Promise<RiskForecast> {
  const { data, error } = await supabase
    .from('risk_forecasts')
    .select('data, generated_at')
    .order('generated_at', { ascending: false })
    .limit(1)
    .single();

  if (error) throw error;
  return normalizeRiskForecastPayload(data?.data, data?.generated_at || null);
}

async function getRiskForecastFromLocalSnapshot(): Promise<RiskForecast | null> {
  const snapshot = await readFirstJsonValue<unknown>(getRiskForecastSnapshotPaths());
  if (!isJsonObject(snapshot)) return null;
  return normalizeRiskForecastPayload(
    snapshot,
    typeof snapshot.generated_at === 'string' ? snapshot.generated_at : null
  );
}

async function loadRiskForecast(): Promise<RiskForecast> {
  const snapshot = await getRiskForecastFromLocalSnapshot();
  if (snapshot) return snapshot;
  return fetchLatestRiskForecast();
}

const getCachedStrategyMetricsPayload = unstable_cache(
  async () => loadStrategyMetricsPayload(false),
  ['strategy-metrics-payload'],
  { revalidate: 300, tags: ['strategy-metrics'] }
);

const getCachedPaperTradesByStrategyInternal = unstable_cache(
  async () => {
    const rows = await fetchPaperTradeRows();
    return buildPaperTradesPayload(rows);
  },
  ['paper-trades-grouped'],
  { revalidate: 86400, tags: ['paper-trades'] }
);

const getCachedStrategyOverviewInternal = unstable_cache(async () => buildStrategyOverview(), ['strategy-overview'], {
  revalidate: 300,
  tags: ['strategy-overview'],
});

const getCachedPortfolioOverviewInternal = unstable_cache(async () => buildPortfolioOverview(), ['portfolio-overview'], {
  revalidate: 300,
  tags: ['portfolio-overview', 'paper-trades', 'strategy-metrics', 'strategy-signals'],
});

const getCachedRiskForecastInternal = unstable_cache(async () => loadRiskForecast(), ['risk-forecast-v2'], {
  revalidate: 900,
  tags: ['risk-forecast'],
});

export async function getFeed(options?: FeedOptions): Promise<FeedListResponse> {
  const hasSearchQuery = Boolean(sanitizeSearchTerm(options?.search));
  if (!hasSearchQuery) {
    const localSnapshot = await getFeedFromLocalSnapshot(options);
    if (localSnapshot) return localSnapshot;
  }

  try {
    return await fetchFeedViaRpc(options);
  } catch (error) {
    if (!isMissingCapabilityError(error)) {
      console.warn('Feed RPC fallback:', error);
    }
    try {
      return await getFeedFromQueries(options);
    } catch {
      const localSnapshot = await getFeedFromLocalSnapshot(options);
      if (localSnapshot) return localSnapshot;
      throw error;
    }
  }
}

export async function getUserBookmarkedArticles(userId: string): Promise<BookmarkedArticleItem[]> {
  const { data: reactionRows, error: reactionError } = await supabase
    .from('article_reactions')
    .select('article_id, created_at')
    .eq('user_id', userId)
    .eq('reaction', 'bookmark')
    .order('created_at', { ascending: false });

  if (reactionError) throw reactionError;

  const rows = (reactionRows || []) as ArticleReactionRow[];
  if (rows.length === 0) return [];

  const orderedIds = rows.map((row) => row.article_id);
  const bookmarkedAtMap = new Map(rows.map((row) => [row.article_id, row.created_at]));

  const { data: articleRows, error: articleError } = await supabase
    .from('articles')
    .select(FEED_ARTICLE_SELECT)
    .in('id', orderedIds)
    .eq('status', 'published');

  if (articleError) throw articleError;

  const articleMap = new Map(
    ((articleRows || []) as ArticleSummaryRow[]).map((row) => [row.id, row])
  );
  const orderedArticles = orderedIds
    .map((id) => articleMap.get(id))
    .filter((row): row is ArticleSummaryRow => Boolean(row));

  const [tagMap, statsMap] = await Promise.all([
    fetchArticleTags(orderedArticles.map((row) => row.id)),
    fetchArticleStats(orderedArticles.map((row) => row.id)),
  ]);

  return orderedArticles.map((article) => ({
    ...toFeedItem(article, tagMap[article.id] || [], statsMap[article.id]),
    bookmarked_at: bookmarkedAtMap.get(article.id) || article.published_at,
  }));
}

export async function getUserQuestions(userId: string): Promise<QuestionItem[]> {
  const { data, error } = await supabase
    .from('questions')
    .select('id, created_at, answered_at, user_id, question, priority, status, answer, proposer, score, current_rank, score_breakdown, prev_rank')
    .eq('source', 'user')
    .eq('user_id', userId)
    .order('created_at', { ascending: false });

  if (error) throw error;

  const rows = (data || []) as QuestionRow[];
  if (rows.length === 0) return [];

  const questionIds = rows.map((row) => row.id);
  const articleMap = await fetchQuestionArticleLinks(questionIds);
  return rows.map((row) => toQuestionItem(row, articleMap[row.id] || []));
}

async function getArticleInternal(slug: string): Promise<FeedItem> {
  const { data, error } = await supabase
    .from('articles')
    .select('*')
    .eq('slug', slug)
    .eq('status', 'published')
    .single();

  if (error) throw error;

  const article = data as ArticleDetailRow;
  const [tagMap, statsMap] = await Promise.all([
    fetchArticleTags([article.id]),
    fetchArticleStats([article.id]),
  ]);

  return toFeedItem(article, tagMap[article.id] || [], statsMap[article.id]);
}

export async function getArticle(slug: string): Promise<FeedItem> {
  const cached = unstable_cache(
    () => getArticleInternal(slug),
    [`article-${slug}`],
    { revalidate: 60, tags: ['article', `article-${slug}`] }
  );
  return cached();
}

export async function getArticleSnapshot(slug: string): Promise<FeedItem | null> {
  const [entries, report] = await Promise.all([
    getLocalFeedEntries(),
    readFirstJsonValue<unknown>(getReportSnapshotPaths(slug)),
  ]);
  const baseEntry = entries?.find((entry) => entry.article.slug === slug) ?? null;
  const reportData = isJsonObject(report) ? (report as LocalFeedRow) : null;
  const derivedEntry = reportData ? buildLocalFeedEntry(reportData) : null;
  const sourceEntry = baseEntry ?? derivedEntry;

  if (!sourceEntry) return null;

  const mergedTags = parseTags([
    ...sourceEntry.tags,
    ...(Array.isArray(reportData?.tags)
      ? reportData.tags.filter((tag): tag is string => typeof tag === 'string')
      : []),
  ]);

  return {
    id: sourceEntry.article.slug,
    slug: sourceEntry.article.slug,
    article_id: sourceEntry.article.id,
    title: sourceEntry.article.title,
    category: typeof reportData?.category === 'string' ? reportData.category : sourceEntry.article.category,
    published_at:
      typeof reportData?.published_at === 'string' ? reportData.published_at : sourceEntry.article.published_at,
    status: typeof reportData?.status === 'string' ? reportData.status : sourceEntry.article.status,
    created_at: sourceEntry.article.created_at ?? undefined,
    summary: typeof reportData?.summary === 'string' ? reportData.summary : undefined,
    content: typeof reportData?.content === 'string' ? reportData.content : undefined,
    description:
      typeof reportData?.description === 'string'
        ? reportData.description
        : sourceEntry.article.excerpt ?? undefined,
    analysis: typeof reportData?.analysis === 'string' ? reportData.analysis : undefined,
    metrics: isJsonObject(reportData?.metrics) ? reportData.metrics : undefined,
    ranking: Array.isArray(reportData?.ranking)
      ? reportData.ranking.filter((row): row is JsonObject => isJsonObject(row))
      : undefined,
    excerpt: sourceEntry.article.excerpt ?? undefined,
    audience: sourceEntry.article.audience ?? undefined,
    phase:
      typeof reportData?.phase === 'string' ? reportData.phase : sourceEntry.article.phase ?? undefined,
    proposer: sourceEntry.article.proposer ?? undefined,
    details: isJsonObject(reportData?.details)
      ? reportData.details
      : sourceEntry.article.details ?? undefined,
    experiment_id: typeof reportData?.experiment_id === 'string' ? reportData.experiment_id : undefined,
    experiment_ids: Array.isArray(reportData?.experiment_ids)
      ? reportData.experiment_ids.filter((value): value is string => typeof value === 'string')
      : undefined,
    tags: mergedTags,
    view_count: 0,
    likes: 0,
  };
}

async function getRelatedArticlesInternal(slug: string, limit: number): Promise<FeedItem[]> {
  const current = await getArticle(slug);

  try {
    const explicitRows = await fetchExplicitRelatedArticles(current.article_id);
    if (explicitRows.length > 0) {
      const limitedRows = explicitRows.slice(0, clampLimit(limit));
      const tagMap = await fetchArticleTags(limitedRows.map((row) => row.id));
      const statsMap = await fetchArticleStats(limitedRows.map((row) => row.id));
      return limitedRows.map((row) => toFeedItem(row, tagMap[row.id] || [], statsMap[row.id]));
    }
  } catch (error) {
    console.warn('Explicit related articles fallback:', error);
  }

  const { data, error } = await supabase
    .from('articles')
    .select(FEED_ARTICLE_SELECT)
    .eq('status', 'published')
    .neq('slug', slug)
    .order('published_at', { ascending: false })
    .limit(RELATED_CANDIDATE_LIMIT);

  if (error) throw error;

  const candidates = (data || []) as ArticleSummaryRow[];
  if (candidates.length === 0) return [];

  const candidateIds = candidates.map((candidate) => candidate.id);
  const tagMap = await fetchArticleTags(candidateIds);
  const currentTags = new Set(current.tags.map(normalizeTag));
  const titleTokens = tokenizeTitle(current.title);

  const scored = candidates
    .map((candidate) => {
      const tags = tagMap[candidate.id] || [];
      let score = 0;

      for (const tag of tags) {
        if (currentTags.has(normalizeTag(tag))) score += 3;
      }

      const candidateTitle = candidate.title.toLowerCase();
      for (const token of titleTokens) {
        if (candidateTitle.includes(token)) score += 1;
      }

      if (current.phase && candidate.phase === current.phase) score += 1;
      if (current.audience && candidate.audience === current.audience) score += 1;

      return { candidate, score };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || b.candidate.published_at.localeCompare(a.candidate.published_at))
    .slice(0, clampLimit(limit));

  if (scored.length === 0) return [];

  const statsMap = await fetchArticleStats(scored.map((entry) => entry.candidate.id));
  return scored.map(({ candidate }) => toFeedItem(candidate, tagMap[candidate.id] || [], statsMap[candidate.id]));
}

export async function getRelatedArticles(slug: string, limit = RELATED_LIMIT, currentArticle?: FeedItem): Promise<FeedItem[]> {
  const cached = unstable_cache(
    () => getRelatedArticlesInternal(slug, limit),
    [`related-articles-${slug}-${limit}`],
    { revalidate: 120, tags: ['related-articles', `related-articles-${slug}`] }
  );
  return cached();
}

export async function getQuestions(source?: string): Promise<QuestionItem[]> {
  let query = supabase
    .from('questions')
    .select('id, created_at, answered_at, user_id, question, priority, status, answer, proposer, score, current_rank, score_breakdown, prev_rank')
    .order('created_at', { ascending: false });

  if (source) query = query.eq('source', source);

  const { data, error } = await query;
  if (error) {
    const fallbackItems = await getQuestionsFromLocalFallback(source);
    if (fallbackItems.length > 0) return fallbackItems;
    throw error;
  }

  const rows = (data || []) as QuestionRow[];
  if (rows.length === 0) {
    const fallbackItems = await getQuestionsFromLocalFallback(source);
    if (fallbackItems.length > 0) return fallbackItems;
  }
  const linkMap = await fetchQuestionArticleLinks(rows.map((row) => row.id));
  return rows.map((row) => toQuestionItem(row, linkMap[row.id] || []));
}

export async function getMemoryEntries(type: string) {
  const { data, error } = await supabase
    .from('memory_entries')
    .select('content')
    .eq('type', type)
    .order('created_at', { ascending: false });

  if (error) throw error;
  return ((data || []) as MemoryEntry[]).map((entry) => entry.content);
}

export async function getResearchSummary() {
  const [experiments, log, knowledge] = await Promise.all([
    getMemoryEntries('experiment'),
    getMemoryEntries('log'),
    getMemoryEntries('knowledge'),
  ]);

  const experimentEntries = experiments.filter(
    (entry): entry is ExperimentEntry =>
      typeof entry === 'object' && entry !== null && !Array.isArray(entry)
  );

  const assets = [...new Set(experimentEntries.map((entry) => entry.asset || '').filter(Boolean))];
  const scored = experimentEntries
    .filter((entry) => typeof entry.metrics?.qlike === 'number' && entry.metrics.qlike < 0)
    .sort((a, b) => (a.metrics?.qlike || 0) - (b.metrics?.qlike || 0))
    .slice(0, 5)
    .map((entry) => ({
      experiment_id: entry.experiment_id || '',
      model_name: entry.model_name || '',
      asset: entry.asset || '',
      qlike: entry.metrics?.qlike || 0,
    }));

  return {
    n_experiments: experiments.length,
    n_log_entries: log.length,
    n_knowledge_items: knowledge.length,
    assets_studied: assets,
    best_models: scored,
  };
}

export async function getRiskForecast(): Promise<RiskForecast> {
  return loadRiskForecast();
}

export async function getRiskForecastCached(): Promise<RiskForecast> {
  return getCachedRiskForecastInternal();
}

export async function getPaperTrades() {
  const { data, error } = await supabase
    .from('paper_trades')
    .select('*')
    .order('trade_date', { ascending: false });

  if (error) throw error;
  return data || [];
}

export async function getPaperTradesByStrategy(options?: { forceFresh?: boolean }): Promise<PaperTradingMap> {
  if (!options?.forceFresh) {
    const localSnapshot = await readLocalPaperTradingPayload();
    if (localSnapshot) return localSnapshot;
  }

  if (options?.forceFresh) {
    const rows = await fetchPaperTradeRows();
    return buildPaperTradesPayload(rows);
  }
  return getCachedPaperTradesByStrategyInternal();
}

async function buildPortfolioOverview(): Promise<PortfolioOverviewResponse> {
  const [paperTradingMap, metricsMap, signals] = await Promise.all([
    getPaperTradesByStrategy(),
    getStrategyMetricsMap(),
    getStrategySignals(),
  ]);

  const items = signals.reduce<PortfolioOverviewStrategy[]>((acc, signal) => {
    const paperTrading = paperTradingMap[signal.strategy_key];
    if (!paperTrading) {
      return acc;
    }

    acc.push({
      strategy_key: signal.strategy_key,
      strategy_name: signal.strategy_name,
      color: signal.color,
      description: signal.description,
      article_links: signal.article_links || [],
      metrics: metricsMap[signal.strategy_key],
      paper_trading: paperTrading,
    });
    return acc;
  }, []);

  return {
    generated_at: new Date().toISOString(),
    items,
  };
}

export async function getPortfolioOverview(options?: { forceFresh?: boolean }): Promise<PortfolioOverviewResponse> {
  if (options?.forceFresh) {
    return buildPortfolioOverview();
  }
  return getCachedPortfolioOverviewInternal();
}

export async function getStrategySignals(): Promise<StrategySignal[]> {
  const rows = await loadStrategySignalRows();
  const identifiers = rows.flatMap((row) =>
    Array.isArray(row.articles)
      ? row.articles.map(extractArticleIdentifier).filter((value): value is string => Boolean(value))
      : []
  );

  const articleLookup = await fetchArticleLinksByIdentifiers(identifiers);
  return rows.map((row) => normalizeStrategySignal(row, articleLookup));
}

export async function getStrategyMetricsMap(options?: { forceFresh?: boolean }): Promise<Record<string, StrategyMetrics>> {
  const payload = options?.forceFresh ? await loadStrategyMetricsPayload(true) : await getCachedStrategyMetricsPayload();
  return Object.fromEntries(
    Object.entries(payload).map(([strategy, value]) => [strategy, value.metrics])
  );
}

export async function refreshStrategyMetricsCache(): Promise<Record<string, StrategyMetrics>> {
  const payload = await loadStrategyMetricsPayload(true);
  return Object.fromEntries(Object.entries(payload).map(([strategy, value]) => [strategy, value.metrics]));
}

export async function getStrategyOverview(options?: { forceFresh?: boolean }): Promise<StrategyOverview> {
  if (!options?.forceFresh) {
    const localSnapshot = await getStrategyOverviewFromLocalSnapshot();
    if (localSnapshot) return localSnapshot;
  }

  if (options?.forceFresh) {
    await loadStrategyMetricsPayload(true);
    return buildStrategyOverview();
  }
  return getCachedStrategyOverviewInternal();
}

export async function replacePaperTrades(payload: SyncPaperTradingPayload): Promise<{ strategies: number; trades: number }> {
  const strategyEntries = Object.entries(payload).filter((entry): entry is [string, SyncPaperTradingStrategy] =>
    isSyncPaperTradingStrategy(entry[1])
  );

  const strategyNames = strategyEntries
    .map(([strategy]) => strategy)
    .filter((strategy) => strategy.trim().length > 0);

  if (strategyNames.length === 0) {
    return { strategies: 0, trades: 0 };
  }

  const { error: deleteError } = await supabase
    .from('paper_trades')
    .delete()
    .in('strategy', strategyNames);

  if (deleteError) throw deleteError;

  const rows: PaperTradeRow[] = [];
  for (const [strategy, strategyPayload] of strategyEntries) {
    if (!strategyNames.includes(strategy)) continue;
    const entries = Array.isArray(strategyPayload.entries) ? strategyPayload.entries : [];
    for (const entry of entries) {
      const tradeDate = normalizeTradeDate(entry);
      if (!tradeDate) continue;
      rows.push({
        strategy,
        entry,
        trade_date: tradeDate,
      });
    }
  }

  for (const batch of chunkArray(rows, 500)) {
    const { error } = await supabase.from('paper_trades').insert(batch);
    if (error) throw error;
  }

  return {
    strategies: strategyNames.length,
    trades: rows.length,
  };
}

async function syncQuestionArticleLinks(articleId: string, details?: JsonObject | null): Promise<void> {
  const questionIds = extractQuestionIds(details);

  try {
    const { error: deleteError } = await supabase
      .from('question_articles')
      .delete()
      .eq('article_id', articleId);

    if (deleteError && !isMissingCapabilityError(deleteError)) throw deleteError;

    if (questionIds.length === 0) return;

    const rows = questionIds.map((questionId) => ({
      question_id: questionId,
      article_id: articleId,
    }));

    const { error: upsertError } = await supabase
      .from('question_articles')
      .upsert(rows, { onConflict: 'question_id,article_id' });

    if (upsertError && !isMissingCapabilityError(upsertError)) throw upsertError;
  } catch (error) {
    if (!isMissingCapabilityError(error)) {
      console.warn('Question/article sync fallback:', error);
    }
  }
}

export async function upsertArticle(article: JsonObject) {
  const { data, error } = await supabase
    .from('articles')
    .upsert(article, { onConflict: 'slug' })
    .select()
    .single();

  if (error) throw error;

  const saved = data as { id: string; details?: JsonObject | null };
  await syncQuestionArticleLinks(saved.id, (saved.details as JsonObject | null | undefined) ?? (article.details as JsonObject | null | undefined));
  return data;
}

export async function upsertRiskForecast(forecast: JsonValue) {
  const { error } = await supabase
    .from('risk_forecasts')
    .insert({ data: forecast });

  if (error) throw error;
}
