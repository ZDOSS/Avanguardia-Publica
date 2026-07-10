import {
  allowMissingCanonicalPoliticianRpcFallback,
  fetchCanonicalLegacyPoliticianRefs,
} from './canonicalPoliticians';
import { supabase } from './supabase';
import { isUuid } from './ids';
import { safeHttpUrl } from './urls';

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

const contactUpdatedAt = (contact: ContactInfo): number => (
  contact.last_updated ? Date.parse(contact.last_updated) || 0 : 0
);

const normalizeContact = (contact: ContactInfo): ContactInfo => ({
  ...contact,
  official_website: safeHttpUrl(contact.official_website),
});

const PROFILE_COLUMNS = 'id, full_name, current_office, party, state, district, last_updated';

export async function fetchProfileHeader(politicianId: string): Promise<ProfileHeader | null> {
  if (!isUuid(politicianId)) return null;

  try {
    return await fetchCanonicalProfileHeader(politicianId);
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, 'get_canonical_politician_header')) {
      throw error;
    }
  }

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
  let canonicalEmptyResult: ContactInfo | null | undefined;

  try {
    const canonicalContact = await fetchCanonicalContactInfo(politicianId);
    if (canonicalContact) return normalizeContact(canonicalContact);
    canonicalEmptyResult = null;
  } catch (error) {
    if (!allowMissingCanonicalPoliticianRpcFallback(error, 'get_canonical_contact_info')) {
      throw error;
    }
  }

  const legacyRefs = await fetchCanonicalLegacyPoliticianRefs(politicianId);
  const legacyPoliticianIds = legacyRefs.map((ref) => ref.legacy_politician_id);
  if (legacyPoliticianIds.length === 0) return canonicalEmptyResult ?? null;

  const canonicalRank = new Map(
    legacyRefs.map((ref, index) => [ref.legacy_politician_id, ref.is_canonical ? 0 : index + 1])
  );

  const { data, error } = await supabase
    .from('contact_info')
    .select('politician_id, office_address, phone_number, official_website, last_updated')
    .in('politician_id', legacyPoliticianIds);

  if (error) {
    if (typeof canonicalEmptyResult !== 'undefined') return canonicalEmptyResult;
    throw error;
  }

  const rows = ((data ?? []) as ContactInfo[]).map(normalizeContact).sort((left, right) => {
    const leftRank = canonicalRank.get(left.politician_id ?? '') ?? Number.MAX_SAFE_INTEGER;
    const rightRank = canonicalRank.get(right.politician_id ?? '') ?? Number.MAX_SAFE_INTEGER;
    return leftRank - rightRank || contactUpdatedAt(right) - contactUpdatedAt(left);
  });

  return rows[0] ?? null;
}

async function fetchCanonicalContactInfo(politicianId: string): Promise<ContactInfo | null> {
  const { data, error } = await supabase.rpc('get_canonical_contact_info', {
    p_id: politicianId,
  });

  if (error) throw error;
  const rows = (data ?? []) as unknown as ContactInfo[];
  return rows[0] ?? null;
}
