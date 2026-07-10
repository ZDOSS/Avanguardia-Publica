import {
  allowMissingCanonicalPoliticianRpcFallback,
  fetchCanonicalLegacyPoliticianIds,
} from './canonicalPoliticians';
import { isUuid } from './ids';
import { pageRange, type PageResult } from './pagination';
import { supabase } from './supabase';

export interface CampaignDonor {
  id: string;
  donation_date: string | null;
  donor_name: string;
  pac_status: boolean | null;
  amount: number;
}

const toNum = (value: unknown): number => (typeof value === 'number' ? value : Number(value ?? 0));

function normalizeDonor(row: CampaignDonor): CampaignDonor {
  return { ...row, amount: toNum(row.amount) };
}

export async function fetchCampaignDonors(
  politicianId: string,
  page = 0,
  pageSize?: number,
): Promise<PageResult<CampaignDonor>> {
  if (!isUuid(politicianId)) return { rows: [], count: 0, page, pageSize: pageSize ?? 25 };
  const range = pageRange(page, pageSize);
  let canonicalEmptyResult: PageResult<CampaignDonor> | null = null;

  try {
    const canonicalResult = await fetchCanonicalCampaignDonors(politicianId, range);
    if (canonicalResult.rows.length > 0 || canonicalResult.hasMore) return canonicalResult;
    canonicalEmptyResult = canonicalResult;
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, 'get_canonical_campaign_donors')) {
      throw error;
    }
  }

  const legacyPoliticianIds = await fetchCanonicalLegacyPoliticianIds(politicianId);
  if (legacyPoliticianIds.length === 0) {
    return canonicalEmptyResult ?? { rows: [], count: 0, page, pageSize: range.pageSize };
  }

  const { data, error, count } = await supabase
    .from('campaign_donors')
    .select('id, donation_date, donor_name, pac_status, amount')
    .in('politician_id', legacyPoliticianIds)
    .order('donation_date', { ascending: false, nullsFirst: false })
    .range(range.from, range.to + 1);

  if (error) {
    if (canonicalEmptyResult) return canonicalEmptyResult;
    throw error;
  }
  const rows = ((data ?? []) as CampaignDonor[]).map(normalizeDonor);
  return {
    rows: rows.slice(0, range.pageSize),
    count,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}

async function fetchCanonicalCampaignDonors(
  politicianId: string,
  range: ReturnType<typeof pageRange>,
): Promise<PageResult<CampaignDonor>> {
  const { data, error } = await supabase.rpc('get_canonical_campaign_donors', {
    p_id: politicianId,
    result_limit: range.pageSize + 1,
    result_offset: range.from,
  });

  if (error) throw error;
  const rows = ((data ?? []) as CampaignDonor[]).map(normalizeDonor);
  return {
    rows: rows.slice(0, range.pageSize),
    count: null,
    hasMore: rows.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}
