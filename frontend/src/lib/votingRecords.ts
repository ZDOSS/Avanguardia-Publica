import { fetchCanonicalLegacyPoliticianIds, missingCanonicalPoliticianRpc } from './canonicalPoliticians';
import { isUuid } from './ids';
import { pageRange, type PageResult } from './pagination';
import { supabase } from './supabase';

export interface VotingRecord {
  id: string;
  bill_name: string;
  bill_summary: string | null;
  vote_date: string;
  vote_cast: string | null;
  jurisdiction: string | null;
  roll_call_id: string | null;
}

export interface VotingRecordFilters {
  voteCast?: string;
}

export async function fetchVotingRecords(
  politicianId: string,
  page = 0,
  pageSize?: number,
  filters: VotingRecordFilters = {},
): Promise<PageResult<VotingRecord>> {
  if (!isUuid(politicianId)) return { rows: [], count: 0, page, pageSize: pageSize ?? 25 };
  const range = pageRange(page, pageSize);
  let canonicalEmptyResult: PageResult<VotingRecord> | null = null;

  try {
    const canonicalResult = await fetchCanonicalVotingRecords(politicianId, range, filters);
    if (canonicalResult.rows.length > 0 || canonicalResult.hasMore) return canonicalResult;
    canonicalEmptyResult = canonicalResult;
  } catch (error) {
    if (!missingCanonicalPoliticianRpc(error as { code?: string; message?: string; details?: string; hint?: string })) {
      throw error;
    }
  }

  const legacyPoliticianIds = await fetchCanonicalLegacyPoliticianIds(politicianId);
  if (legacyPoliticianIds.length === 0) {
    return canonicalEmptyResult ?? { rows: [], count: 0, page, pageSize: range.pageSize };
  }

  let query = supabase
    .from('voting_records')
    .select('id, bill_name, bill_summary, vote_date, vote_cast, jurisdiction, roll_call_id')
    .in('politician_id', legacyPoliticianIds)
    .order('vote_date', { ascending: false })
    .range(range.from, range.to + 1);

  if (filters.voteCast) {
    query = query.eq('vote_cast', filters.voteCast);
  }

  const { data, error, count } = await query;
  if (error) {
    if (canonicalEmptyResult) return canonicalEmptyResult;
    throw error;
  }
  const rows = (data ?? []) as VotingRecord[];
  return {
    rows: rows.slice(0, range.pageSize),
    count,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}

async function fetchCanonicalVotingRecords(
  politicianId: string,
  range: ReturnType<typeof pageRange>,
  filters: VotingRecordFilters,
): Promise<PageResult<VotingRecord>> {
  const { data, error } = await supabase.rpc('get_canonical_voting_records', {
    p_id: politicianId,
    result_limit: range.pageSize + 1,
    result_offset: range.from,
    vote_cast_filter: filters.voteCast || null,
  });

  if (error) throw error;
  const rows = (data ?? []) as VotingRecord[];
  return {
    rows: rows.slice(0, range.pageSize),
    count: null,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}
