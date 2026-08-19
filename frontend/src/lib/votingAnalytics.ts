import { isUuid } from './ids';
import { pageRange, type PageResult } from './pagination';
import { supabase } from './supabase';
import { safeHttpUrl } from './urls';
import {
  normalizeLegislativeMeasures,
  type LegislativeMeasure,
} from './votingRecords';

export type FederalChamber = 'house' | 'senate';
export type FederalVotingComparisonFilter = 'agree' | 'differ';

export interface FederalVotingSummary {
  person_id: string;
  chamber: FederalChamber;
  congress: number;
  first_vote_date: string;
  last_vote_date: string;
  covered_vote_count: number;
  participating_vote_count: number;
  substantive_vote_count: number;
  yea_count: number;
  nay_count: number;
  present_count: number;
  not_voting_count: number;
  participation_rate: number;
  alignment_minimum_shared_votes: number;
  source_name: string;
  source_updated_at: string | null;
}

export interface FederalVotingAlignment {
  peer_person_id: string;
  full_name: string;
  current_office: string | null;
  party: string | null;
  state: string | null;
  district: string | null;
  chamber: FederalChamber;
  congress: number;
  agree_count: number;
  differ_count: number;
  shared_substantive_count: number;
  agreement_rate: number;
  first_shared_vote_date: string;
  last_shared_vote_date: string;
  aligned_rank: number;
  differing_rank: number;
  source_name: string;
  source_updated_at: string | null;
}

export interface FederalVotingComparison {
  roll_call_id: string;
  chamber: FederalChamber;
  congress: number;
  session: number;
  roll_call_number: number;
  vote_date: string;
  question: string;
  vote_result: string | null;
  person_vote_cast: 'Yea' | 'Nay';
  peer_vote_cast: 'Yea' | 'Nay';
  comparison: FederalVotingComparisonFilter;
  source_name: string;
  source_url: string | null;
  source_updated_at: string | null;
  measures: LegislativeMeasure[];
}

type UnknownRow = Record<string, unknown>;

function optionalText(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed || null;
}

function numberValue(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function integerValue(value: unknown): number {
  return Math.trunc(numberValue(value));
}

function boundedRate(value: unknown): number {
  return Math.min(1, Math.max(0, numberValue(value)));
}

function chamberValue(value: unknown): FederalChamber | null {
  return value === 'house' || value === 'senate' ? value : null;
}

function normalizeSummary(row: UnknownRow): FederalVotingSummary | null {
  const personId = optionalText(row.person_id);
  const chamber = chamberValue(row.chamber);
  const congress = integerValue(row.congress);
  const firstVoteDate = optionalText(row.first_vote_date);
  const lastVoteDate = optionalText(row.last_vote_date);
  const sourceName = optionalText(row.source_name);

  if (
    !personId
    || !isUuid(personId)
    || !chamber
    || congress <= 0
    || !firstVoteDate
    || !lastVoteDate
    || !sourceName
  ) {
    return null;
  }

  return {
    person_id: personId,
    chamber,
    congress,
    first_vote_date: firstVoteDate,
    last_vote_date: lastVoteDate,
    covered_vote_count: integerValue(row.covered_vote_count),
    participating_vote_count: integerValue(row.participating_vote_count),
    substantive_vote_count: integerValue(row.substantive_vote_count),
    yea_count: integerValue(row.yea_count),
    nay_count: integerValue(row.nay_count),
    present_count: integerValue(row.present_count),
    not_voting_count: integerValue(row.not_voting_count),
    participation_rate: boundedRate(row.participation_rate),
    alignment_minimum_shared_votes: Math.max(
      1,
      integerValue(row.alignment_minimum_shared_votes),
    ),
    source_name: sourceName,
    source_updated_at: optionalText(row.source_updated_at),
  };
}

function normalizeAlignment(row: UnknownRow): FederalVotingAlignment | null {
  const peerPersonId = optionalText(row.peer_person_id);
  const fullName = optionalText(row.full_name);
  const chamber = chamberValue(row.chamber);
  const congress = integerValue(row.congress);
  const firstSharedVoteDate = optionalText(row.first_shared_vote_date);
  const lastSharedVoteDate = optionalText(row.last_shared_vote_date);
  const sourceName = optionalText(row.source_name);

  if (
    !peerPersonId
    || !isUuid(peerPersonId)
    || !fullName
    || !chamber
    || congress <= 0
    || !firstSharedVoteDate
    || !lastSharedVoteDate
    || !sourceName
  ) {
    return null;
  }

  return {
    peer_person_id: peerPersonId,
    full_name: fullName,
    current_office: optionalText(row.current_office),
    party: optionalText(row.party),
    state: optionalText(row.state),
    district: optionalText(row.district),
    chamber,
    congress,
    agree_count: integerValue(row.agree_count),
    differ_count: integerValue(row.differ_count),
    shared_substantive_count: integerValue(row.shared_substantive_count),
    agreement_rate: boundedRate(row.agreement_rate),
    first_shared_vote_date: firstSharedVoteDate,
    last_shared_vote_date: lastSharedVoteDate,
    aligned_rank: Math.max(1, integerValue(row.aligned_rank)),
    differing_rank: Math.max(1, integerValue(row.differing_rank)),
    source_name: sourceName,
    source_updated_at: optionalText(row.source_updated_at),
  };
}

function normalizeComparison(row: UnknownRow): FederalVotingComparison | null {
  const rollCallId = optionalText(row.roll_call_id);
  const chamber = chamberValue(row.chamber);
  const congress = integerValue(row.congress);
  const session = integerValue(row.session);
  const rollCallNumber = integerValue(row.roll_call_number);
  const voteDate = optionalText(row.vote_date);
  const question = optionalText(row.question);
  const personVoteCast = row.person_vote_cast;
  const peerVoteCast = row.peer_vote_cast;
  const comparison = row.comparison;
  const sourceName = optionalText(row.source_name);

  if (
    !rollCallId
    || !chamber
    || congress <= 0
    || session <= 0
    || rollCallNumber <= 0
    || !voteDate
    || !question
    || (personVoteCast !== 'Yea' && personVoteCast !== 'Nay')
    || (peerVoteCast !== 'Yea' && peerVoteCast !== 'Nay')
    || (comparison !== 'agree' && comparison !== 'differ')
    || !sourceName
  ) {
    return null;
  }

  return {
    roll_call_id: rollCallId,
    chamber,
    congress,
    session,
    roll_call_number: rollCallNumber,
    vote_date: voteDate,
    question,
    vote_result: optionalText(row.vote_result),
    person_vote_cast: personVoteCast,
    peer_vote_cast: peerVoteCast,
    comparison,
    source_name: sourceName,
    source_url: safeHttpUrl(optionalText(row.source_url)),
    source_updated_at: optionalText(row.source_updated_at),
    measures: normalizeLegislativeMeasures(row.measures),
  };
}

export async function fetchFederalVotingSummaries(
  politicianId: string,
): Promise<FederalVotingSummary[]> {
  if (!isUuid(politicianId)) return [];

  const { data, error } = await supabase.rpc(
    'get_canonical_federal_voting_summary_v1',
    { p_id: politicianId },
  );
  if (error) throw error;

  return ((data ?? []) as UnknownRow[]).flatMap((row) => {
    const normalized = normalizeSummary(row);
    return normalized ? [normalized] : [];
  });
}

export async function fetchFederalVotingAlignment(
  politicianId: string,
  chamber: FederalChamber,
  congress: number,
  resultLimitPerSide = 6,
): Promise<FederalVotingAlignment[]> {
  if (!isUuid(politicianId) || congress <= 0) return [];

  const { data, error } = await supabase.rpc(
    'get_canonical_federal_voting_alignment_v1',
    {
      p_id: politicianId,
      scope_chamber: chamber,
      scope_congress: congress,
      result_limit_per_side: Math.min(
        12,
        Math.max(1, Math.trunc(resultLimitPerSide)),
      ),
    },
  );
  if (error) throw error;

  return ((data ?? []) as UnknownRow[]).flatMap((row) => {
    const normalized = normalizeAlignment(row);
    return normalized ? [normalized] : [];
  });
}

export async function fetchLatestFederalVotingAlignment(
  politicianId: string,
  resultLimitPerSide = 6,
): Promise<{
  summary: FederalVotingSummary | null;
  peers: FederalVotingAlignment[];
}> {
  const summaries = await fetchFederalVotingSummaries(politicianId);
  const summary = summaries[0] ?? null;
  if (!summary) return { summary: null, peers: [] };

  const peers = await fetchFederalVotingAlignment(
    politicianId,
    summary.chamber,
    summary.congress,
    resultLimitPerSide,
  );
  return { summary, peers };
}

export async function fetchFederalVotingComparison(
  politicianId: string,
  peerId: string,
  chamber: FederalChamber,
  congress: number,
  page = 0,
  pageSize?: number,
  filter?: FederalVotingComparisonFilter,
): Promise<PageResult<FederalVotingComparison>> {
  const range = pageRange(page, pageSize);
  if (!isUuid(politicianId) || !isUuid(peerId) || politicianId === peerId) {
    return { rows: [], count: 0, page: range.page, pageSize: range.pageSize };
  }

  const { data, error } = await supabase.rpc(
    'get_canonical_federal_voting_comparison_v1',
    {
      p_id: politicianId,
      peer_id: peerId,
      scope_chamber: chamber,
      scope_congress: congress,
      comparison_filter: filter ?? null,
      result_limit: range.pageSize + 1,
      result_offset: range.from,
    },
  );
  if (error) throw error;

  const normalized = ((data ?? []) as UnknownRow[]).flatMap((row) => {
    const comparison = normalizeComparison(row);
    return comparison ? [comparison] : [];
  });

  return {
    rows: normalized.slice(0, range.pageSize),
    count: null,
    hasMore: normalized.length > range.pageSize,
    page: range.page,
    pageSize: range.pageSize,
  };
}
