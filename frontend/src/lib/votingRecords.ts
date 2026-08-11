import {
  allowMissingCanonicalPoliticianRpcFallback,
  fetchCanonicalLegacyPoliticianIds,
} from './canonicalPoliticians';
import { isUuid } from './ids';
import { pageRange, type PageResult } from './pagination';
import { supabase } from './supabase';
import { safeHttpUrl } from './urls';

export interface VotingRecord {
  id: string;
  bill_name: string;
  bill_summary: string | null;
  vote_date: string;
  vote_cast: string | null;
  jurisdiction: string | null;
  roll_call_id: string | null;
  record_origin: 'official' | 'legacy';
  chamber: 'house' | 'senate' | null;
  congress: number | null;
  session: number | null;
  roll_call_number: number | null;
  vote_result: string | null;
  source_name: string | null;
  source_url: string | null;
  source_updated_at: string | null;
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

  try {
    return await fetchCanonicalVotingRecordsV2(politicianId, range, filters);
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, 'get_canonical_voting_records_v2')) {
      throw error;
    }
  }

  // Local-development compatibility for a database that has not applied migration
  // 0031 yet. Production fails closed above so an unapplied public read contract
  // cannot silently hide official facts.
  let canonicalEmptyResult: PageResult<VotingRecord> | null = null;

  try {
    const canonicalResult = await fetchCanonicalVotingRecords(politicianId, range, filters);
    if (canonicalResult.rows.length > 0 || canonicalResult.hasMore) return canonicalResult;
    canonicalEmptyResult = canonicalResult;
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, 'get_canonical_voting_records')) {
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
  const rows = normalizeVotingRecords(data ?? []);
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
  const rows = normalizeVotingRecords(data ?? []);
  return {
    rows: rows.slice(0, range.pageSize),
    count: null,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}

async function fetchCanonicalVotingRecordsV2(
  politicianId: string,
  range: ReturnType<typeof pageRange>,
  filters: VotingRecordFilters,
): Promise<PageResult<VotingRecord>> {
  const { data, error } = await supabase.rpc('get_canonical_voting_records_v2', {
    p_id: politicianId,
    result_limit: range.pageSize + 1,
    result_offset: range.from,
    vote_cast_filter: filters.voteCast || null,
  });

  if (error) throw error;
  const rows = normalizeVotingRecords(data ?? []);
  return {
    rows: rows.slice(0, range.pageSize),
    count: null,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}

type VotingRecordRow = Partial<VotingRecord> & Pick<VotingRecord, 'id' | 'bill_name' | 'vote_date'>;

function normalizeVotingRecords(data: unknown[]): VotingRecord[] {
  return (data as VotingRecordRow[]).map((row) => ({
    id: row.id,
    bill_name: row.bill_name,
    bill_summary: row.bill_summary ?? null,
    vote_date: row.vote_date,
    vote_cast: row.vote_cast ?? null,
    jurisdiction: row.jurisdiction ?? null,
    roll_call_id: row.roll_call_id ?? null,
    record_origin: row.record_origin === 'official' ? 'official' : 'legacy',
    chamber: row.chamber === 'house' || row.chamber === 'senate' ? row.chamber : null,
    congress: typeof row.congress === 'number' ? row.congress : null,
    session: typeof row.session === 'number' ? row.session : null,
    roll_call_number: typeof row.roll_call_number === 'number' ? row.roll_call_number : null,
    vote_result: row.vote_result ?? null,
    source_name: row.source_name ?? null,
    source_url: safeHttpUrl(row.source_url),
    source_updated_at: row.source_updated_at ?? null,
  }));
}
