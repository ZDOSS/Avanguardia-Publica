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

  const { data, error, count } = await supabase
    .from('campaign_donors')
    .select('id, donation_date, donor_name, pac_status, amount', { count: 'exact' })
    .eq('politician_id', politicianId)
    .order('donation_date', { ascending: false, nullsFirst: false })
    .range(range.from, range.to);

  if (error) throw error;
  return {
    rows: ((data ?? []) as CampaignDonor[]).map(normalizeDonor),
    count,
    page: range.page,
    pageSize: range.pageSize,
  };
}
