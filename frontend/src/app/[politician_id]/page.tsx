import { notFound } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import ProfilePageClient from '@/app/profile/ProfilePageClient';
import PoliticianClient from './PoliticianClient';
import type { PoliticianData } from './PoliticianClient';

const MOCK_STATIC_PARAMS = [
  { politician_id: 'biden-joe' },
  { politician_id: 'harris-kamala' },
];

function allowMockProfileBuild(): boolean {
  return process.env.ALLOW_MOCK_BUILD === 'true';
}

// This function runs at build time on GitHub Actions
export async function generateStaticParams() {
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
    if (allowMockProfileBuild()) {
      console.warn('Supabase build credentials are absent; using explicit local/CI fixture routes.');
      return MOCK_STATIC_PARAMS;
    }
    throw new Error('No Supabase URL or anon key configured for the production export.');
  }

  try {
    // Supabase caps a single response at 1,000 rows, so page through every
    // politician — otherwise profiles past the first 1,000 would never get a
    // static page generated and would 404 once the dataset grows (state/local).
    const PAGE_SIZE = 1000;
    const params: { politician_id: string }[] = [];
    for (let from = 0; ; from += PAGE_SIZE) {
      const { data, error } = await supabase
        .from('politicians')
        .select('id')
        .order('id')
        .range(from, from + PAGE_SIZE - 1);
      if (error) throw error;
      if (!data || data.length === 0) break;
      params.push(...data.map((politician) => ({ politician_id: politician.id })));
      if (data.length < PAGE_SIZE) break;
    }

    if (params.length === 0) {
      if (allowMockProfileBuild()) return MOCK_STATIC_PARAMS;
      throw new Error('Supabase returned zero politicians; refusing to publish an empty production export.');
    }
    return params;
  } catch (e) {
    console.error("Failed to generate static params:", e);
    if (allowMockProfileBuild()) return MOCK_STATIC_PARAMS;
    throw e;
  }
}

// Next.js page component
export default async function Page(props: { params: Promise<{ politician_id: string }> }) {
  const params = await props.params;
  const { politician_id } = params;

  const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(politician_id);

  // Every generated legacy UUID is a static alias shell. The browser resolves it through
  // the canonical header RPC, avoiding one build-time database request per profile while
  // ensuring duplicate legacy IDs display the same person identity.
  if (isUUID) {
    return <ProfilePageClient profileId={politician_id} />;
  }

  let politician: PoliticianData | null = null;
  if (['biden-joe', 'harris-kamala'].includes(politician_id)) {
    // Return standard mock profile only for the explicit local/CI fixture paths.
    politician = {
        id: politician_id,
        full_name: politician_id === 'biden-joe' ? 'Joe Biden (Mock)' : 'Kamala Harris (Mock)',
        current_office: politician_id === 'biden-joe' ? 'President of the United States' : 'Vice President of the United States',
        party: 'Democratic',
        state: null,
        district: null,
        last_updated: null,
        contact_info: [{
          office_address: '1600 Pennsylvania Ave NW',
          phone_number: '202-456-1111',
          official_website: 'https://www.whitehouse.gov',
          last_updated: null,
        }],
    };
  } else {
    // Safe logging of the non-UUID politician_id to prevent log injection.
    console.warn(`Non-UUID politician ID detected: ${JSON.stringify(politician_id.slice(0, 100))}. Skipping database query.`);
    notFound();
  }

  // Pass data to the interactive client component
  return <PoliticianClient politician={politician} />;
}
