import { supabase } from './supabase';

// Live cross-reference "Connections" API. These wrap the Postgres RPC functions added
// in migrations/0003_connections.sql, which compute connections on demand from the
// existing spokes. Called client-side in the browser (the static export ships only the
// page shell; data is fetched live, like the directory) — no precomputed table.

export interface SharedDonorConnection {
  politician_id: string;
  full_name: string;
  current_office: string | null;
  party: string | null;
  shared_donor_count: number;
  shared_total_amount: number;
}

export interface CoVoteConnection {
  politician_id: string;
  full_name: string;
  current_office: string | null;
  party: string | null;
  agree_count: number;
  disagree_count: number;
  shared_total: number;
  agreement_rate: number; // 0..1
}

export interface NetworkTie {
  related_name: string;
  related_politician_id: string | null; // set only on an exact match to a tracked profile
  relationship_type: string | null;
  source_api: string | null;
  url: string | null;
}

export interface ConnectionsBundle {
  sharedDonors: SharedDonorConnection[];
  coVotes: CoVoteConnection[];
  networkTies: NetworkTie[];
}

async function rpc<T>(fn: string, politicianId: string): Promise<T[]> {
  const { data, error } = await supabase.rpc(fn, { p_id: politicianId });
  if (error) throw error;
  return (data ?? []) as T[];
}

/**
 * Fetch all three connection types for a politician in parallel.
 *
 * Each lane fails independently: a failure of one RPC — most likely the unverified
 * `get_network_ties` (third-party LittleSis) lane — must NOT hide the verified
 * shared-donor and co-voting lanes. We log per-lane failures and render whatever
 * succeeded, and only throw when *every* lane fails (a real outage worth surfacing as an
 * error state instead of a misleadingly empty view).
 */
export async function fetchConnections(politicianId: string): Promise<ConnectionsBundle> {
  const [donors, votes, ties] = await Promise.allSettled([
    rpc<SharedDonorConnection>('get_shared_donors', politicianId),
    rpc<CoVoteConnection>('get_covoting', politicianId),
    rpc<NetworkTie>('get_network_ties', politicianId),
  ]);

  const lanes = [
    ['get_shared_donors', donors],
    ['get_covoting', votes],
    ['get_network_ties', ties],
  ] as const;

  if (lanes.every(([, r]) => r.status === 'rejected')) {
    throw (donors as PromiseRejectedResult).reason;
  }
  for (const [name, r] of lanes) {
    if (r.status === 'rejected') console.error(`Connections RPC ${name} failed:`, r.reason);
  }

  return {
    sharedDonors: donors.status === 'fulfilled' ? donors.value : [],
    coVotes: votes.status === 'fulfilled' ? votes.value : [],
    networkTies: ties.status === 'fulfilled' ? ties.value : [],
  };
}
