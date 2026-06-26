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

  let query = supabase
    .from('voting_records')
    .select('id, bill_name, bill_summary, vote_date, vote_cast, jurisdiction, roll_call_id')
    .eq('politician_id', politicianId)
    .order('vote_date', { ascending: false })
    .range(range.from, range.to + 1);

  if (filters.voteCast) {
    query = query.eq('vote_cast', filters.voteCast);
  }

  const { data, error, count } = await query;
  if (error) throw error;
  const rows = (data ?? []) as VotingRecord[];
  return {
    rows: rows.slice(0, range.pageSize),
    count,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}
