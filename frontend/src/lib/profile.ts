import { missingCanonicalPoliticianRpc } from './canonicalPoliticians';
import { supabase } from './supabase';
import { isUuid } from './ids';

export interface ProfileHeader {
  id: string;
  full_name: string;
  current_office: string | null;
  party: string | null;
  state: string | null;
  district: string | null;
  last_updated: string | null;
}

export interface ContactInfo {
  politician_id?: string;
  office_address: string | null;
  phone_number: string | null;
  official_website: string | null;
  last_updated: string | null;
}

const PROFILE_COLUMNS = 'id, full_name, current_office, party, state, district, last_updated';

export async function fetchProfileHeader(politicianId: string): Promise<ProfileHeader | null> {
  if (!isUuid(politicianId)) return null;

  try {
    return await fetchCanonicalProfileHeader(politicianId);
  } catch (error) {
    if (!missingCanonicalPoliticianRpc(error as { code?: string; message?: string; details?: string; hint?: string })) {
      throw error;
    }
  }

  return fetchRawProfileHeader(politicianId);
}

export async function fetchStaticProfileHeader(politicianId: string): Promise<ProfileHeader | null> {
  if (!isUuid(politicianId)) return null;
  return fetchRawProfileHeader(politicianId);
}

async function fetchCanonicalProfileHeader(politicianId: string): Promise<ProfileHeader | null> {
  const { data, error } = await supabase.rpc('get_canonical_politician_header', {
    p_id: politicianId,
  });

  if (error) throw error;
  const rows = (data ?? []) as unknown as ProfileHeader[];
  return rows[0] ?? null;
}

async function fetchRawProfileHeader(politicianId: string): Promise<ProfileHeader | null> {
  const { data, error } = await supabase
    .from('politicians')
    .select(PROFILE_COLUMNS)
    .eq('id', politicianId)
    .maybeSingle();

  if (error) throw error;
  return (data ?? null) as ProfileHeader | null;
}

export async function fetchContactInfo(politicianId: string): Promise<ContactInfo | null> {
  if (!isUuid(politicianId)) return null;

  try {
    return await fetchCanonicalContactInfo(politicianId);
  } catch (error) {
    if (!missingCanonicalPoliticianRpc(error as { code?: string; message?: string; details?: string; hint?: string })) {
      throw error;
    }
  }

  const { data, error } = await supabase
    .from('contact_info')
    .select('*')
    .eq('politician_id', politicianId)
    .maybeSingle();

  if (error) throw error;
  return (data ?? null) as ContactInfo | null;
}

async function fetchCanonicalContactInfo(politicianId: string): Promise<ContactInfo | null> {
  const { data, error } = await supabase.rpc('get_canonical_contact_info', {
    p_id: politicianId,
  });

  if (error) throw error;
  const rows = (data ?? []) as unknown as ContactInfo[];
  return rows[0] ?? null;
}
