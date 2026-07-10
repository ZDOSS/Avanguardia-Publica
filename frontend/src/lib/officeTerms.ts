import { allowMissingCanonicalPoliticianRpcFallback } from './canonicalPoliticians';
import { isUuid } from './ids';
import { supabase } from './supabase';

export interface PersonOfficeTerm {
  id: string;
  person_id: string;
  source_record_id: string;
  source_system_key: string;
  source_record_key: string;
  source_url: string | null;
  office_title: string;
  role_type: string | null;
  organization_name: string | null;
  government_level: string | null;
  government_branch: string | null;
  office_type: string | null;
  jurisdiction: string | null;
  state: string | null;
  district: string | null;
  term_start: string | null;
  term_end: string | null;
  term_status: string;
  verified_lane: string;
  last_seen_at: string | null;
}

export async function fetchPersonOfficeTerms(profileId: string): Promise<PersonOfficeTerm[]> {
  if (!isUuid(profileId)) return [];

  const { data, error } = await supabase.rpc('get_canonical_person_office_terms', {
    p_id: profileId,
  });

  if (error) {
    if (allowMissingCanonicalPoliticianRpcFallback(error, 'get_canonical_person_office_terms')) {
      return [];
    }
    throw error;
  }

  return (data ?? []) as PersonOfficeTerm[];
}
