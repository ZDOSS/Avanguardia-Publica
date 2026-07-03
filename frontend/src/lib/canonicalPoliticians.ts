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
