import { supabase } from './supabase';
import { safeHttpUrl } from './urls';
import {
  fetchLatestFederalVotingAlignment,
  type FederalChamber,
  type FederalVotingSummary,
} from './votingAnalytics';

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
  record_origin: 'official' | 'legacy';
  chamber: FederalChamber | null;
  congress: number | null;
  aligned_rank: number | null;
  differing_rank: number | null;
  first_shared_vote_date: string | null;
  last_shared_vote_date: string | null;
  source_name: string | null;
}

export interface NetworkTie {
  related_name: string;
  related_politician_id: string | null; // set only on an exact match to a tracked profile
  relationship_type: string; // NOT NULL in the schema (defaults to 'Connection')
  source_api: string;        // NOT NULL in the schema (defaults to 'LittleSis')
  url: string | null;
}

export type ConnectionLane = 'sharedDonors' | 'coVotes' | 'networkTies';

export interface ConnectionLaneFailure {
  lane: ConnectionLane;
  label: string;
}

export interface ConnectionsBundle {
  sharedDonors: SharedDonorConnection[];
  coVotes: CoVoteConnection[];
  federalVotingSummary: FederalVotingSummary | null;
  networkTies: NetworkTie[];
  failures: ConnectionLaneFailure[];
}

async function rpc<T>(fn: string, politicianId: string): Promise<T[]> {
  const { data, error } = await supabase.rpc(fn, { p_id: politicianId });
  if (error) throw error;
  return (data ?? []) as T[];
}

// PostgREST serializes Postgres `numeric` AND `bigint` as JSON strings (to avoid JS
// precision loss), so COUNT/SUM/ROUND columns arrive as e.g. "5" / "1234.5". Coerce them
// to real numbers at the boundary so the `number` interface types are truthful and
// downstream code is correct — notably strict checks like `count === 1` (a string "1"
// would never === 1, silently breaking pluralization).
const toNum = (v: unknown): number => (typeof v === 'number' ? v : Number(v ?? 0));

function normalizeDonor(d: SharedDonorConnection): SharedDonorConnection {
  return { ...d, shared_donor_count: toNum(d.shared_donor_count), shared_total_amount: toNum(d.shared_total_amount) };
}

function normalizeLegacyCoVote(c: CoVoteConnection): CoVoteConnection {
  return {
    ...c,
    agree_count: toNum(c.agree_count),
    disagree_count: toNum(c.disagree_count),
    shared_total: toNum(c.shared_total),
    agreement_rate: toNum(c.agreement_rate),
    record_origin: 'legacy',
    chamber: null,
    congress: null,
    aligned_rank: null,
    differing_rank: null,
    first_shared_vote_date: null,
    last_shared_vote_date: null,
    source_name: null,
  };
}

async function fetchVotingConnections(politicianId: string): Promise<{
  rows: CoVoteConnection[];
  summary: FederalVotingSummary | null;
}> {
  const official = await fetchLatestFederalVotingAlignment(politicianId);
  if (official.summary) {
    return {
      summary: official.summary,
      rows: official.peers.map((peer) => ({
        politician_id: peer.peer_person_id,
        full_name: peer.full_name,
        current_office: peer.current_office,
        party: peer.party,
        agree_count: peer.agree_count,
        disagree_count: peer.differ_count,
        shared_total: peer.shared_substantive_count,
        agreement_rate: peer.agreement_rate,
        record_origin: 'official',
        chamber: peer.chamber,
        congress: peer.congress,
        aligned_rank: peer.aligned_rank,
        differing_rank: peer.differing_rank,
        first_shared_vote_date: peer.first_shared_vote_date,
        last_shared_vote_date: peer.last_shared_vote_date,
        source_name: peer.source_name,
      })),
    };
  }

  const legacy = await rpc<CoVoteConnection>('get_covoting', politicianId);
  return { summary: null, rows: legacy.map(normalizeLegacyCoVote) };
}

function normalizeTie(tie: NetworkTie): NetworkTie {
  return { ...tie, url: safeHttpUrl(tie.url) };
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
    fetchVotingConnections(politicianId),
    rpc<NetworkTie>('get_network_ties', politicianId),
  ]);

  const lanes = [
    ['get_shared_donors', donors],
    ['federal voting analytics / get_covoting', votes],
    ['get_network_ties', ties],
  ] as const;

  if (lanes.every(([, r]) => r.status === 'rejected')) {
    throw (donors as PromiseRejectedResult).reason;
  }
  for (const [name, r] of lanes) {
    if (r.status === 'rejected') console.error(`Connections RPC ${name} failed:`, r.reason);
  }

  const failures: ConnectionLaneFailure[] = [];
  if (donors.status === 'rejected') failures.push({ lane: 'sharedDonors', label: 'Shared donors' });
  if (votes.status === 'rejected') failures.push({ lane: 'coVotes', label: 'Voting comparisons' });
  if (ties.status === 'rejected') failures.push({ lane: 'networkTies', label: 'Third-party network ties' });

  return {
    sharedDonors: donors.status === 'fulfilled' ? donors.value.map(normalizeDonor) : [],
    coVotes: votes.status === 'fulfilled' ? votes.value.rows : [],
    federalVotingSummary: votes.status === 'fulfilled' ? votes.value.summary : null,
    networkTies: ties.status === 'fulfilled' ? ties.value.map(normalizeTie) : [],
    failures,
  };
}
