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

  const { data, error, count } = await supabase
    .from('unconfirmed_mentions')
    .select('id, source_api, sentiment_score, content_summary, url, created_at', { count: 'exact' })
    .eq('politician_id', politicianId)
    .order('created_at', { ascending: false })
    .range(range.from, range.to);

  if (error) throw error;
  return {
    rows: ((data ?? []) as MediaMention[]).map(normalizeMention),
    count,
    page: range.page,
    pageSize: range.pageSize,
  };
}
