import { supabase } from './supabase';
import type { PoliticianData, UnconfirmedMention } from '@/app/[politician_id]/PoliticianClient';

export interface LiveProfileBundle {
  politician: PoliticianData;
  unconfirmed: UnconfirmedMention[];
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

export async function fetchLiveProfile(politicianId: string): Promise<LiveProfileBundle | null> {
  if (!isUuid(politicianId)) return null;

  const { data: politician, error: politicianError } = await supabase
    .from('politicians')
    .select('*, contact_info(*), financial_disclosures(*), campaign_donors(*), voting_records(*)')
    .eq('id', politicianId)
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
