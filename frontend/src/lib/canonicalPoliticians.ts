import { isUuid } from './ids';
import { supabase } from './supabase';

const CANONICAL_POLITICIAN_RPC_NAMES = [
  'resolve_canonical_politician_ids',
  'get_canonical_politician_summaries',
  'get_canonical_politician_header',
  'get_canonical_person_legacy_ids',
  'get_canonical_contact_info',
  'get_canonical_financial_disclosures',
  'get_canonical_campaign_donors',
  'get_canonical_voting_records',
  'get_canonical_media_mentions',
];

interface SupabaseErrorLike {
  code?: string;
  message?: string;
  details?: string;
  hint?: string;
}

export interface CanonicalLegacyPoliticianRef {
  legacy_politician_id: string;
  is_canonical: boolean;
}

export function missingCanonicalPoliticianRpc(error: SupabaseErrorLike | null): boolean {
  if (!error) return false;

  const text = [
    error.code,
    error.message,
    error.details,
    error.hint,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  const referencesCanonicalRpc = CANONICAL_POLITICIAN_RPC_NAMES.some((name) =>
    text.includes(name)
  );
  const missingFunction =
    text.includes('pgrst202') ||
    text.includes('42883') ||
    text.includes('could not find') ||
    text.includes('does not exist') ||
    text.includes('schema cache');

  return referencesCanonicalRpc && missingFunction;
}

export async function fetchCanonicalLegacyPoliticianRefs(profileId: string): Promise<CanonicalLegacyPoliticianRef[]> {
  if (!isUuid(profileId)) return [];

  try {
    const { data, error } = await supabase.rpc('get_canonical_person_legacy_ids', {
      profile_id: profileId,
    });

    if (error) throw error;

    const seen = new Set<string>();
    const refs = ((data ?? []) as { legacy_politician_id?: string | null; is_canonical?: boolean | null }[])
      .filter((row) => typeof row.legacy_politician_id === 'string' && isUuid(row.legacy_politician_id))
      .flatMap((row) => {
        const id = row.legacy_politician_id as string;
        if (seen.has(id)) return [];
        seen.add(id);
        return [{ legacy_politician_id: id, is_canonical: row.is_canonical === true }];
      });

    return refs.length > 0 ? refs : [{ legacy_politician_id: profileId, is_canonical: true }];
  } catch (error) {
    if (missingCanonicalPoliticianRpc(error as SupabaseErrorLike)) {
      return [{ legacy_politician_id: profileId, is_canonical: true }];
    }
    throw error;
  }
}

export async function fetchCanonicalLegacyPoliticianIds(profileId: string): Promise<string[]> {
  const refs = await fetchCanonicalLegacyPoliticianRefs(profileId);
  return refs.map((ref) => ref.legacy_politician_id);
}
