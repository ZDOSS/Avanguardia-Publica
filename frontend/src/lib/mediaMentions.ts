import { missingCanonicalPoliticianRpc } from './canonicalPoliticians';
import { isUuid } from './ids';
import { pageRange, type PageResult } from './pagination';
import { supabase } from './supabase';

export interface MediaMention {
  id: string;
  source_api: string;
  sentiment_score: number | null;
  content_summary: string;
  url: string | null;
  created_at: string | null;
}

const toNullableNum = (value: unknown): number | null => {
  if (value === null || typeof value === 'undefined') return null;
  return typeof value === 'number' ? value : Number(value);
};

function normalizeMention(row: MediaMention): MediaMention {
  return { ...row, sentiment_score: toNullableNum(row.sentiment_score) };
}

export async function fetchMediaMentions(
  politicianId: string,
  page = 0,
  pageSize?: number,
): Promise<PageResult<MediaMention>> {
  if (!isUuid(politicianId)) return { rows: [], count: 0, page, pageSize: pageSize ?? 25 };
  const range = pageRange(page, pageSize);

  try {
    return await fetchCanonicalMediaMentions(politicianId, range);
  } catch (error) {
    if (!missingCanonicalPoliticianRpc(error as { code?: string; message?: string; details?: string; hint?: string })) {
      throw error;
    }
  }

  const { data, error, count } = await supabase
    .from('unconfirmed_mentions')
    .select('id, source_api, sentiment_score, content_summary, url, created_at')
    .eq('politician_id', politicianId)
    .order('created_at', { ascending: false })
    .range(range.from, range.to + 1);

  if (error) throw error;
  const rows = ((data ?? []) as MediaMention[]).map(normalizeMention);
  return {
    rows: rows.slice(0, range.pageSize),
    count,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}

async function fetchCanonicalMediaMentions(
  politicianId: string,
  range: ReturnType<typeof pageRange>,
): Promise<PageResult<MediaMention>> {
  const { data, error } = await supabase.rpc('get_canonical_media_mentions', {
    p_id: politicianId,
    result_limit: range.pageSize + 1,
    result_offset: range.from,
  });

  if (error) throw error;
  const rows = ((data ?? []) as MediaMention[]).map(normalizeMention);
  return {
    rows: rows.slice(0, range.pageSize),
    count: null,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}
