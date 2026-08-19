import {
  allowMissingCanonicalPoliticianRpcFallback,
  fetchCanonicalLegacyPoliticianIds,
  missingCanonicalPoliticianRpc,
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
  measures: LegislativeMeasure[];
}

export type LegislativeMeasureKind = 'bill' | 'amendment';

export type LegislativeMeasureType =
  | 'hr'
  | 's'
  | 'hjres'
  | 'sjres'
  | 'hconres'
  | 'sconres'
  | 'hres'
  | 'sres'
  | 'hamdt'
  | 'samdt'
  | 'suamdt';

export interface LegislativeMeasure {
  canonical_measure_key: string;
  measure_kind: LegislativeMeasureKind;
  congress: number;
  measure_type: LegislativeMeasureType;
  measure_number: number;
  title: string | null;
  purpose: string | null;
  official_url: string | null;
  source_name: string | null;
  observed_at: string | null;
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
    return await fetchCanonicalVotingRecordsV3(politicianId, range, filters);
  } catch (error) {
    // Keep the existing v2 vote surface live during the short deployment window
    // before migration 0037 is applied. Scraper preflight requires 0037, so this
    // optional metadata fallback cannot become silent long-term schema drift.
    if (!missingCanonicalPoliticianRpc(error)) throw error;
  }

  try {
    return await fetchCanonicalVotingRecordsV2(politicianId, range, filters);
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, 'get_canonical_voting_records_v2')) {
      throw error;
    }
  }

  // Local-development compatibility for a database that has not applied the
  // official-vote read migrations yet. Production fails closed above so drift
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

async function fetchCanonicalVotingRecordsV3(
  politicianId: string,
  range: ReturnType<typeof pageRange>,
  filters: VotingRecordFilters,
): Promise<PageResult<VotingRecord>> {
  const { data, error } = await supabase.rpc('get_canonical_voting_records_v3', {
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
  return (data as VotingRecordRow[]).map((row) => {
    const recordOrigin = row.record_origin === 'official' ? 'official' : 'legacy';

    return {
      id: row.id,
      bill_name: row.bill_name,
      bill_summary: row.bill_summary ?? null,
      vote_date: row.vote_date,
      vote_cast: row.vote_cast ?? null,
      jurisdiction: row.jurisdiction ?? null,
      roll_call_id: row.roll_call_id ?? null,
      record_origin: recordOrigin,
      chamber: row.chamber === 'house' || row.chamber === 'senate' ? row.chamber : null,
      congress: typeof row.congress === 'number' ? row.congress : null,
      session: typeof row.session === 'number' ? row.session : null,
      roll_call_number: typeof row.roll_call_number === 'number' ? row.roll_call_number : null,
      vote_result: row.vote_result ?? null,
      source_name: row.source_name ?? null,
      source_url: safeHttpUrl(row.source_url),
      source_updated_at: row.source_updated_at ?? null,
      measures: recordOrigin === 'official' ? normalizeLegislativeMeasures(row.measures) : [],
    };
  });
}

const LEGISLATIVE_MEASURE_TYPES = new Set<LegislativeMeasureType>([
  'hr',
  's',
  'hjres',
  'sjres',
  'hconres',
  'sconres',
  'hres',
  'sres',
  'hamdt',
  'samdt',
  'suamdt',
]);

function optionalText(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed || null;
}

export function normalizeLegislativeMeasures(value: unknown): LegislativeMeasure[] {
  if (!Array.isArray(value)) return [];

  const measures: LegislativeMeasure[] = [];
  const seen = new Set<string>();

  for (const candidate of value.slice(0, 100)) {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) continue;
    const row = candidate as Record<string, unknown>;
    const canonicalMeasureKey = optionalText(row.canonical_measure_key);
    const measureKind = row.measure_kind;
    const measureType = row.measure_type;
    const congress = row.congress;
    const measureNumber = row.measure_number;

    if (
      !canonicalMeasureKey
      || (measureKind !== 'bill' && measureKind !== 'amendment')
      || typeof measureType !== 'string'
      || !LEGISLATIVE_MEASURE_TYPES.has(measureType as LegislativeMeasureType)
      || typeof congress !== 'number'
      || !Number.isInteger(congress)
      || congress <= 0
      || typeof measureNumber !== 'number'
      || !Number.isInteger(measureNumber)
      || measureNumber <= 0
    ) {
      continue;
    }

    const expectedKey = `${measureKind}:${congress}:${measureType}:${measureNumber}`;
    if (canonicalMeasureKey !== expectedKey || seen.has(canonicalMeasureKey)) continue;
    seen.add(canonicalMeasureKey);

    measures.push({
      canonical_measure_key: canonicalMeasureKey,
      measure_kind: measureKind,
      congress,
      measure_type: measureType as LegislativeMeasureType,
      measure_number: measureNumber,
      title: optionalText(row.title),
      purpose: optionalText(row.purpose),
      official_url: safeHttpUrl(optionalText(row.official_url)),
      source_name: optionalText(row.source_name),
      observed_at: optionalText(row.observed_at),
    });
  }

  return measures;
}
