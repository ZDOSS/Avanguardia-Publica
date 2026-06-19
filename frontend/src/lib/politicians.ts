import { supabase } from './supabase';

export interface PoliticianSummary {
  id: string;
  full_name: string;
  current_office: string;
  party: string;
  state: string | null;
  district: string | null;
}

const SUMMARY_COLUMNS = "id, full_name, current_office, party, state, district";

// Supabase/PostgREST caps every response at `max-rows` (1,000 by default).
// Crucially, `.limit(n)` does NOT raise that cap — a `.limit(10000)` request is
// still silently truncated to 1,000 rows. The only reliable way to read the full
// table is to page through it with `.range()`, which is what this helper does.
const PAGE_SIZE = 1000;

/**
 * Fetch every politician summary, paging past Supabase's per-response row cap.
 *
 * Throws on any database error so callers can surface it (rather than rendering a
 * silently truncated directory).
 */
export async function fetchAllPoliticians(): Promise<PoliticianSummary[]> {
  const all: PoliticianSummary[] = [];

  for (let from = 0; ; from += PAGE_SIZE) {
    const { data, error } = await supabase
      .from('politicians')
      .select(SUMMARY_COLUMNS)
      .order('full_name')
      .range(from, from + PAGE_SIZE - 1);

    if (error) throw error;
    if (!data || data.length === 0) break;

    all.push(...(data as PoliticianSummary[]));

    // A short page means we've reached the end of the table.
    if (data.length < PAGE_SIZE) break;
  }

  return all;
}
