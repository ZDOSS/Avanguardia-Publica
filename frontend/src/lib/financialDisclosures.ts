import { isUuid } from './ids';
import { pageRange, type PageResult } from './pagination';
import { supabase } from './supabase';

export interface FinancialDisclosure {
  id: string;
  filing_date: string;
  filing_type: string | null;
  doc_url: string | null;
  doc_id: string | null;
}

export async function fetchFinancialDisclosures(
  politicianId: string,
  page = 0,
  pageSize?: number,
): Promise<PageResult<FinancialDisclosure>> {
  if (!isUuid(politicianId)) return { rows: [], count: 0, page, pageSize: pageSize ?? 25 };
  const range = pageRange(page, pageSize);

  const { data, error, count } = await supabase
    .from('financial_disclosures')
    .select('id, filing_date, filing_type, doc_url, doc_id')
    .eq('politician_id', politicianId)
    .order('filing_date', { ascending: false })
    .range(range.from, range.to + 1);

  if (error) throw error;
  const rows = (data ?? []) as FinancialDisclosure[];
  return {
    rows: rows.slice(0, range.pageSize),
    count,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}
