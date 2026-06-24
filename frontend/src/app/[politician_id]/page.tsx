import { notFound } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import PoliticianClient from './PoliticianClient';
import type { PoliticianData } from './PoliticianClient';

// This function runs at build time on GitHub Actions
export async function generateStaticParams() {
  try {
    if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
      throw new Error("No Supabase URL or Anon Key configured. Using mock IDs.");
    }
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

    if (params.length === 0) return [{ politician_id: 'biden-joe' }, { politician_id: 'harris-kamala' }];
    return params;
  } catch (e) {
    console.error("Failed to generate static params:", e);
    if (process.env.CI === 'true' || process.env.GITHUB_ACTIONS === 'true') {
      throw e;
    }
    // Return mock ID for local testing
    return [{ politician_id: 'biden-joe' }, { politician_id: 'harris-kamala' }];
  }
}

// Next.js page component
export default async function Page(props: { params: Promise<{ politician_id: string }> }) {
  const params = await props.params;
  const { politician_id } = params;

  // We fetch the data on the server side at build time for the static export
  let politician: PoliticianData | null = null;

  const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(politician_id);

  try {
    if (isUUID) {
      if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
        throw new Error("No Supabase URL or Anon Key configured.");
      }
      
      const { data: polData, error: polError } = await supabase
        .from('politicians')
        .select('id, full_name, current_office, party, state, district, last_updated')
        .eq('id', politician_id)
        .maybeSingle();
        
      if (polError) throw polError;
      if (polData) {
        politician = polData;
      }

    } else {
      // Safe logging of the non-UUID politician_id to prevent log injection
      console.warn(`Non-UUID politician ID detected: ${JSON.stringify(politician_id.slice(0, 100))}. Skipping database query.`);
    }
  } catch (e) {
    console.error("Error fetching politician page data:", e);
    // Do not swallow DB errors; throw them so Next.js serves a 500 error 
    // instead of a 404, preventing search engines from de-indexing valid pages.
    throw e;
  }

  // If we couldn't fetch (e.g. no DB connection or politician doesn't exist), fallback or 404
  if (!politician) {
    if (['biden-joe', 'harris-kamala'].includes(politician_id)) {
      // Return standard mock profile only for the explicit mock paths
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
      // Trigger Next.js native 404 for invalid pages in production
      notFound();
    }
  }

  // Pass data to the interactive client component
  return <PoliticianClient politician={politician} />;
}
