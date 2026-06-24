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

  const { data, error } = await supabase
    .from('contact_info')
    .select('*')
    .eq('politician_id', politicianId)
    .maybeSingle();

  if (error) throw error;
  return (data ?? null) as ContactInfo | null;
}
