import { allowMissingCanonicalPoliticianRpcFallback } from './canonicalPoliticians';
import { supabase } from './supabase';

export interface PoliticianSummary {
  id: string;
  full_name: string;
  current_office: string;
  party: string;
  state: string | null;
  district: string | null;
  government_level: string | null;
  government_branch: string | null;
  office_type: string | null;
  jurisdiction: string | null;
}

type BasePoliticianSummary = Omit<
  PoliticianSummary,
  "government_level" | "government_branch" | "office_type" | "jurisdiction"
>;

const BASE_SUMMARY_COLUMNS = "id, full_name, current_office, party, state, district";
const SUMMARY_COLUMNS = `${BASE_SUMMARY_COLUMNS}, government_level, government_branch, office_type, jurisdiction`;
const CLASSIFICATION_COLUMNS = ["government_level", "government_branch", "office_type", "jurisdiction"];

// Supabase/PostgREST caps every response at `max-rows` (1,000 by default).
// Crucially, `.limit(n)` does NOT raise that cap — a `.limit(10000)` request is
// still silently truncated to 1,000 rows. The only reliable way to read the full
// table is to page through it with `.range()`, which is what this helper does.
const PAGE_SIZE = 1000;
const DEFAULT_SEARCH_LIMIT = 25;
const CANONICAL_SUMMARIES_RPC = 'get_canonical_politician_summaries';

function missingClassificationColumn(error: { code?: string; message?: string; details?: string } | null): boolean {
  if (!error) return false;
  const text = `${error.code ?? ""} ${error.message ?? ""} ${error.details ?? ""}`.toLowerCase();
  return text.includes("pgrst204") && CLASSIFICATION_COLUMNS.some((column) => text.includes(column));
}

function withEmptyClassification(rows: BasePoliticianSummary[] | null): PoliticianSummary[] {
  return (rows ?? []).map((row) => ({
    ...row,
    government_level: null,
    government_branch: null,
    office_type: null,
    jurisdiction: null,
  }));
}

export async function fetchPoliticianSummaries(limit = 6): Promise<PoliticianSummary[]> {
  try {
    return await fetchCanonicalPoliticianSummaries({ limit });
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, CANONICAL_SUMMARIES_RPC)) {
      throw error;
    }
  }

  return fetchPoliticianSummariesFromTable(limit);
}

async function fetchPoliticianSummariesFromTable(limit: number): Promise<PoliticianSummary[]> {
  const { data, error } = await supabase
    .from('politicians')
    .select(SUMMARY_COLUMNS)
    .order('full_name')
    .limit(limit);

  if (missingClassificationColumn(error)) {
    const fallback = await supabase
      .from('politicians')
      .select(BASE_SUMMARY_COLUMNS)
      .order('full_name')
      .limit(limit);

    if (fallback.error) throw fallback.error;
    return withEmptyClassification(fallback.data as unknown as BasePoliticianSummary[]);
  }

  if (error) throw error;
  return (data ?? []) as unknown as PoliticianSummary[];
}

export async function searchPoliticians(
  query: string,
  limit = DEFAULT_SEARCH_LIMIT,
): Promise<PoliticianSummary[]> {
  const trimmed = query.trim();
  if (!trimmed) return [];

  try {
    return await fetchCanonicalPoliticianSummaries({ searchQuery: trimmed, limit });
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, CANONICAL_SUMMARIES_RPC)) {
      throw error;
    }
  }

  const { data, error } = await supabase
    .from('politicians')
    .select(SUMMARY_COLUMNS)
    .textSearch('search_vector', trimmed, { type: 'websearch', config: 'english' })
    .order('full_name')
    .limit(limit);

  if (missingClassificationColumn(error)) {
    const fallback = await supabase
      .from('politicians')
      .select(BASE_SUMMARY_COLUMNS)
      .textSearch('search_vector', trimmed, { type: 'websearch', config: 'english' })
      .order('full_name')
      .limit(limit);

    if (fallback.error) throw fallback.error;
    return withEmptyClassification(fallback.data as unknown as BasePoliticianSummary[]);
  }

  if (error) throw error;
  return (data ?? []) as unknown as PoliticianSummary[];
}

/**
 * Fetch every politician summary, paging past Supabase's per-response row cap.
 *
 * Throws on any database error so callers can surface it (rather than rendering a
 * silently truncated directory).
 */
export async function fetchAllPoliticians(): Promise<PoliticianSummary[]> {
  try {
    return await fetchAllCanonicalPoliticians();
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, CANONICAL_SUMMARIES_RPC)) {
      throw error;
    }
  }

  try {
    return await fetchAllPoliticiansWithColumns(SUMMARY_COLUMNS, true);
  } catch (error) {
    if (!missingClassificationColumn(error as { code?: string; message?: string; details?: string })) {
      throw error;
    }
    return fetchAllPoliticiansWithColumns(BASE_SUMMARY_COLUMNS, false);
  }
}

async function fetchCanonicalPoliticianSummaries({
  searchQuery = null,
  limit,
  offset = 0,
}: {
  searchQuery?: string | null;
  limit: number;
  offset?: number;
}): Promise<PoliticianSummary[]> {
  const { data, error } = await supabase.rpc(CANONICAL_SUMMARIES_RPC, {
    search_query: searchQuery,
    result_limit: limit,
    result_offset: offset,
  });

  if (error) throw error;
  return (data ?? []) as unknown as PoliticianSummary[];
}

async function fetchAllCanonicalPoliticians(): Promise<PoliticianSummary[]> {
  const all: PoliticianSummary[] = [];

  for (let offset = 0; ; offset += PAGE_SIZE) {
    const page = await fetchCanonicalPoliticianSummaries({ limit: PAGE_SIZE, offset });
    all.push(...page);
    if (page.length < PAGE_SIZE) break;
  }

  return all;
}

async function fetchAllPoliticiansWithColumns(
  columns: string,
  includesClassification: boolean,
): Promise<PoliticianSummary[]> {
  const all: PoliticianSummary[] = [];

  for (let from = 0; ; from += PAGE_SIZE) {
    const { data, error } = await supabase
      .from('politicians')
      .select(columns)
      .order('full_name')
      .range(from, from + PAGE_SIZE - 1);

    if (error) throw error;
    if (!data || data.length === 0) break;

    const page = includesClassification
      ? (data as unknown as PoliticianSummary[])
      : withEmptyClassification(data as unknown as BasePoliticianSummary[]);
    all.push(...page);

    // A short page means we've reached the end of the table.
    if (data.length < PAGE_SIZE) break;
  }

  return all;
}
