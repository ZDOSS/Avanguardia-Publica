import { supabase } from '@/lib/supabase';
import PoliticianClient from './PoliticianClient';

// This function runs at build time on GitHub Actions
export async function generateStaticParams() {
  try {
    if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
      throw new Error("No Supabase URL or Anon Key configured. Using mock IDs.");
    }
    const { data } = await supabase.from('politicians').select('id');
    if (!data || data.length === 0) return [{ politician_id: 'biden-joe' }, { politician_id: 'harris-kamala' }];
    
    return data.map((politician) => ({
      politician_id: politician.id,
    }));
  } catch (e) {
    console.error("Failed to generate static params:", e);
    // Return mock ID for local testing
    return [{ politician_id: 'biden-joe' }, { politician_id: 'harris-kamala' }];
  }
}

// Next.js page component
export default async function Page(props: { params: Promise<{ politician_id: string }> }) {
  const params = await props.params;
  const { politician_id } = params;

  // We fetch the data on the server side at build time for the static export
  let politician = null;
  let unconfirmed = [];

  try {
    if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
      throw new Error("No Supabase URL or Anon Key configured. Falling back to mock data.");
    }
    const { data: polData } = await supabase
      .from('politicians')
      .select('*, contact_info(*), financial_disclosures(*), campaign_donors(*), voting_records(*)')
      .eq('id', politician_id)
      .single();
      
    if (polData) {
      politician = polData;
    }

    const { data: mentions } = await supabase
      .from('unconfirmed_mentions')
      .select('*')
      .eq('politician_id', politician_id)
      .order('created_at', { ascending: false });

    if (mentions) {
      unconfirmed = mentions;
    }
  } catch (e) {
    console.error(e);
  }

  // If we couldn't fetch (e.g. no env vars during local dev), use mock data
  if (!politician) {
    politician = {
      id: politician_id,
      full_name: 'Mock Politician (No DB Connection)',
      current_office: 'Unknown Office',
      party: 'Independent',
      contact_info: [{ office_address: '123 Fake St', phone_number: '555-0199', official_website: 'https://example.com' }],
      financial_disclosures: [],
      campaign_donors: [],
      voting_records: []
    };
  }

  // Pass data to the interactive client component
  return <PoliticianClient politician={politician} unconfirmed={unconfirmed} />;
}
