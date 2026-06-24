import { supabase } from './supabase';
import { isUuid } from './ids';
import type { PoliticianData, UnconfirmedMention } from '@/app/[politician_id]/PoliticianClient';

export interface LiveProfileBundle {
  politician: PoliticianData;
  unconfirmed: UnconfirmedMention[];
}

const PROFILE_RELATED_ROW_LIMIT = 100;

export async function fetchLiveProfile(politicianId: string): Promise<LiveProfileBundle | null> {
  if (!isUuid(politicianId)) return null;

  const { data: politician, error: politicianError } = await supabase
    .from('politicians')
    .select('*, contact_info(*), financial_disclosures(*), campaign_donors(*), voting_records(*)')
    .eq('id', politicianId)
    .order('filing_date', { referencedTable: 'financial_disclosures', ascending: false })
    .limit(PROFILE_RELATED_ROW_LIMIT, { referencedTable: 'financial_disclosures' })
    .order('donation_date', { referencedTable: 'campaign_donors', ascending: false })
    .limit(PROFILE_RELATED_ROW_LIMIT, { referencedTable: 'campaign_donors' })
    .order('vote_date', { referencedTable: 'voting_records', ascending: false })
    .limit(PROFILE_RELATED_ROW_LIMIT, { referencedTable: 'voting_records' })
    .maybeSingle();

  if (politicianError) throw politicianError;
  if (!politician) return null;

  const { data: unconfirmed, error: mentionsError } = await supabase
    .from('unconfirmed_mentions')
    .select('*')
    .eq('politician_id', politicianId)
    .order('created_at', { ascending: false });

  if (mentionsError) throw mentionsError;

  return {
    politician: politician as PoliticianData,
    unconfirmed: (unconfirmed ?? []) as UnconfirmedMention[],
  };
}
