"use client";

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { DEFAULT_PROFILE_PAGE_SIZE, emptyPage, type PageResult } from '@/lib/pagination';
import { profilePath } from '@/lib/routes';
import {
  fetchFederalVotingAlignment,
  fetchFederalVotingComparison,
  fetchFederalVotingSummaries,
  type FederalVotingAlignment,
  type FederalVotingComparison,
  type FederalVotingComparisonFilter,
  type FederalVotingSummary,
} from '@/lib/votingAnalytics';
import type { LegislativeMeasure, LegislativeMeasureType } from '@/lib/votingRecords';
import { formatDate, PaginationControls } from './ProfileSpokeStates';

const MEASURE_TYPE_LABELS: Record<LegislativeMeasureType, string> = {
  hr: 'H.R.',
  s: 'S.',
  hjres: 'H.J.Res.',
  sjres: 'S.J.Res.',
  hconres: 'H.Con.Res.',
  sconres: 'S.Con.Res.',
  hres: 'H.Res.',
  sres: 'S.Res.',
  hamdt: 'H.Amdt.',
  samdt: 'S.Amdt.',
  suamdt: 'Senate unprinted amendment',
};

function scopeKey(summary: Pick<FederalVotingSummary, 'chamber' | 'congress'>): string {
  return `${summary.chamber}:${summary.congress}`;
}

function chamberLabel(chamber: FederalVotingSummary['chamber']): string {
  return chamber === 'house' ? 'U.S. House' : 'U.S. Senate';
}

function initialComparisonPeer(): string | null {
  if (typeof window === 'undefined') return null;
  const candidate = new URLSearchParams(window.location.search).get('compare');
  return candidate && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(candidate)
    ? candidate
    : null;
}

function updateComparisonUrl(peerId: string | null) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  if (peerId) url.searchParams.set('compare', peerId);
  else url.searchParams.delete('compare');
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

function percentage(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function measureLabel(measure: LegislativeMeasure): string {
  return `${MEASURE_TYPE_LABELS[measure.measure_type]} ${measure.measure_number}`;
}

function SummaryCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="premium-card p-4">
      <div className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-text-muted)]">
        {label}
      </div>
      <div className="mt-2 text-2xl font-extrabold text-[var(--color-official-text)]">{value}</div>
      <div className="mt-1 text-xs text-[var(--color-official-text-muted)]">{detail}</div>
    </div>
  );
}

function PeerCard({
  peer,
  rankKind,
  selected,
  onCompare,
}: {
  peer: FederalVotingAlignment;
  rankKind: 'aligned' | 'differing';
  selected: boolean;
  onCompare: () => void;
}) {
  const rank = rankKind === 'aligned' ? peer.aligned_rank : peer.differing_rank;
  const count = rankKind === 'aligned' ? peer.agree_count : peer.differ_count;

  return (
    <article
      className={`premium-card p-4 ${selected ? 'border-[var(--color-official-link)]' : ''}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-text-muted)]">
            #{rank} {rankKind === 'aligned' ? 'most aligned' : 'most often differed'}
          </p>
          <h4 className="mt-1 font-bold text-[var(--color-official-text)]">{peer.full_name}</h4>
          <p className="text-xs text-[var(--color-official-text-muted)]">
            {[peer.current_office, peer.party].filter(Boolean).join(' · ') || 'Office details unavailable'}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full border border-[var(--color-official-border)] bg-[var(--color-official-bg)] px-3 py-1 text-xs font-bold ${
            rankKind === 'aligned'
              ? 'text-[var(--color-official-link)]'
              : 'text-[var(--color-warning-badge)]'
          }`}
        >
          {percentage(peer.agreement_rate)} aligned
        </span>
      </div>
      <p className="mt-3 text-xs font-mono text-[var(--color-official-text-muted)]">
        {peer.agree_count} same · {peer.differ_count} different · {peer.shared_substantive_count} shared Yea/Nay votes
      </p>
      <p className="mt-1 text-xs text-[var(--color-official-text-muted)]">
        {count} recorded {rankKind === 'aligned' ? 'agreements' : 'differences'} from {formatDate(peer.first_shared_vote_date)} to {formatDate(peer.last_shared_vote_date)}
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onCompare}
          className="min-h-11 rounded-full bg-[var(--color-official-link)] px-4 text-sm font-bold text-white transition-opacity hover:opacity-90 cursor-pointer"
        >
          {selected ? 'Viewing comparison' : 'Compare shared votes'}
        </button>
        <Link
          href={profilePath(peer.peer_person_id)}
          className="inline-flex min-h-11 items-center rounded-full border border-[var(--color-official-border)] px-4 text-sm font-bold text-[var(--color-official-link)] hover:border-[var(--color-official-link)]"
        >
          Open profile
        </Link>
      </div>
    </article>
  );
}

function ComparisonMeasure({ measure }: { measure: LegislativeMeasure }) {
  return (
    <div className="rounded-xl border border-[var(--color-official-border)] bg-[var(--color-official-bg)] p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
        <span className="font-bold text-[var(--color-official-link)]">{measureLabel(measure)}</span>
        {measure.official_url && (
          <a
            href={measure.official_url}
            target="_blank"
            rel="noreferrer"
            className="font-bold text-[var(--color-official-link)] hover:underline"
          >
            Congress.gov
          </a>
        )}
      </div>
      {measure.title && <p className="mt-2 text-sm font-semibold">{measure.title}</p>}
      {measure.purpose && measure.purpose !== measure.title && (
        <p className="mt-1 text-sm text-[var(--color-official-text-muted)]">Purpose: {measure.purpose}</p>
      )}
    </div>
  );
}

function ComparisonRecordCard({
  record,
  peerName,
  politicianName,
}: {
  record: FederalVotingComparison;
  peerName: string;
  politicianName: string;
}) {
  const agrees = record.comparison === 'agree';

  return (
    <article className="premium-card p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2 text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
            <span className={`font-bold ${agrees ? 'text-[var(--color-official-link)]' : 'text-[var(--color-warning-badge)]'}`}>
              {agrees ? 'Agreement' : 'Different votes'}
            </span>
            <span>{formatDate(record.vote_date)}</span>
            <span>Roll call {record.roll_call_number}</span>
            <span>Session {record.session}</span>
          </div>
          <h5 className="mt-2 text-lg font-bold leading-tight">{record.question}</h5>
          {record.vote_result && (
            <p className="mt-1 text-sm text-[var(--color-official-text-muted)]">Result: {record.vote_result}</p>
          )}
        </div>
        <div className="grid shrink-0 grid-cols-2 gap-2 text-center text-xs">
          <div className="rounded-lg border border-[var(--color-official-border)] bg-[var(--color-official-bg)] px-3 py-2">
            <span
              className="block max-w-28 truncate text-[var(--color-official-text-muted)]"
              title={politicianName}
            >
              {politicianName}
            </span>
            <strong>{record.person_vote_cast}</strong>
          </div>
          <div className="rounded-lg border border-[var(--color-official-border)] bg-[var(--color-official-bg)] px-3 py-2">
            <span className="block max-w-28 truncate text-[var(--color-official-text-muted)]" title={peerName}>{peerName}</span>
            <strong>{record.peer_vote_cast}</strong>
          </div>
        </div>
      </div>
      {record.measures.length > 0 && (
        <div className="mt-4 grid gap-2">
          {record.measures.map((measure) => (
            <ComparisonMeasure key={measure.canonical_measure_key} measure={measure} />
          ))}
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3 text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
        <span>{chamberLabel(record.chamber)} · Congress {record.congress}</span>
        {record.source_url ? (
          <a
            href={record.source_url}
            target="_blank"
            rel="noreferrer"
            className="font-bold text-[var(--color-official-link)] hover:underline"
          >
            Source: {record.source_name}
          </a>
        ) : (
          <span>Source: {record.source_name}</span>
        )}
      </div>
    </article>
  );
}

function ComparisonPanel({
  politicianId,
  politicianName,
  peer,
  summary,
  onClose,
}: {
  politicianId: string;
  politicianName: string;
  peer: FederalVotingAlignment;
  summary: FederalVotingSummary;
  onClose: () => void;
}) {
  const peerId = peer.peer_person_id;
  const peerName = peer.full_name;
  const [filter, setFilter] = useState<FederalVotingComparisonFilter | ''>('');
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<PageResult<FederalVotingComparison> | null>(null);
  const [loading, setLoading] = useState(Boolean(peerId));
  const [error, setError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!peerId) return;
    let cancelled = false;
    fetchFederalVotingComparison(
      politicianId,
      peerId,
      summary.chamber,
      summary.congress,
      page,
      DEFAULT_PROFILE_PAGE_SIZE,
      filter || undefined,
    )
      .then((nextResult) => {
        if (!cancelled) {
          setResult(nextResult);
          setError(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          console.error('Failed to load federal voting comparison:', e);
          setError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [filter, page, peerId, politicianId, retryKey, summary.chamber, summary.congress]);

  const changeFilter = (next: FederalVotingComparisonFilter | '') => {
    setFilter(next);
    setPage(0);
    setResult(null);
    setLoading(true);
    setError(false);
  };

  const changePage = (nextPage: number) => {
    setPage(nextPage);
    setResult(null);
    setLoading(true);
    setError(false);
  };

  const current = result ?? emptyPage<FederalVotingComparison>(page);

  return (
    <section className="scroll-mt-24 rounded-2xl border border-[var(--color-official-link)]/40 bg-[var(--color-official-bg-alt)] p-4 sm:p-6" aria-labelledby="voting-comparison-heading">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-link)]">Official pairwise evidence</p>
          <h3 id="voting-comparison-heading" className="mt-1 text-2xl font-extrabold">Shared votes with {peerName}</h3>
          <p className="mt-2 max-w-3xl text-sm text-[var(--color-official-text-muted)]">
            Only exact shared Yea/Nay votes from {chamberLabel(summary.chamber)} in Congress {summary.congress} are compared. Present and Not Voting do not affect alignment.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="min-h-11 shrink-0 rounded-full border border-[var(--color-official-border)] px-4 text-sm font-bold hover:border-[var(--color-official-link)] cursor-pointer"
        >
          Close comparison
        </button>
      </div>

      <div className="mt-5 flex flex-wrap gap-2" role="group" aria-label="Comparison filter">
        {([
          ['', 'All shared votes'],
          ['agree', 'Agreements'],
          ['differ', 'Differences'],
        ] as const).map(([value, label]) => (
          <button
            key={value || 'all'}
            type="button"
            aria-pressed={filter === value}
            onClick={() => changeFilter(value)}
            className={`min-h-11 rounded-full border px-4 text-sm font-bold cursor-pointer ${
              filter === value
                ? 'border-[var(--color-official-link)] bg-[var(--color-official-link)] text-white'
                : 'border-[var(--color-official-border)] text-[var(--color-official-text-muted)] hover:border-[var(--color-official-link)]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {loading && !result ? (
        <div className="mt-5 animate-pulse space-y-3">
          <div className="h-36 premium-card" />
          <div className="h-36 premium-card" />
        </div>
      ) : error && !result ? (
        <div className="mt-5 premium-card p-6 text-center">
          <p className="font-semibold text-[var(--color-warning-badge)]">Could not load the shared-vote evidence.</p>
          <button
            type="button"
            onClick={() => {
              setLoading(true);
              setError(false);
              setRetryKey((value) => value + 1);
            }}
            className="mt-3 min-h-11 rounded-full border border-[var(--color-official-border)] px-4 text-sm font-bold text-[var(--color-official-link)] hover:border-[var(--color-official-link)] cursor-pointer"
          >
            Retry comparison
          </button>
        </div>
      ) : current.rows.length === 0 ? (
        <div className="mt-5 premium-card p-6 text-center text-[var(--color-official-text-muted)]">
          No {filter === 'agree' ? 'agreements' : filter === 'differ' ? 'differences' : 'shared substantive votes'} were found in this scope.
        </div>
      ) : (
        <div className="mt-5 space-y-4">
          {current.rows.map((record) => (
            <ComparisonRecordCard
              key={record.roll_call_id}
              record={record}
              peerName={peerName}
              politicianName={politicianName}
            />
          ))}
          {error && (
            <p className="text-sm text-[var(--color-warning-badge)]">Could not refresh this comparison page.</p>
          )}
          <PaginationControls result={current} onPage={changePage} />
        </div>
      )}
    </section>
  );
}

export default function VotingAnalyticsPanel({
  politicianId,
  politicianName,
}: {
  politicianId: string;
  politicianName: string;
}) {
  const [summaries, setSummaries] = useState<FederalVotingSummary[] | null>(null);
  const [selectedScopeKey, setSelectedScopeKey] = useState<string | null>(null);
  const [alignment, setAlignment] = useState<FederalVotingAlignment[] | null>(null);
  const [selectedPeerId, setSelectedPeerId] = useState<string | null>(initialComparisonPeer);
  const [summaryError, setSummaryError] = useState(false);
  const [alignmentError, setAlignmentError] = useState(false);
  const [summaryRetryKey, setSummaryRetryKey] = useState(0);
  const [alignmentRetryKey, setAlignmentRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchFederalVotingSummaries(politicianId)
      .then((nextSummaries) => {
        if (cancelled) return;
        setSummaries(nextSummaries);
        setSummaryError(false);
        setSelectedScopeKey((currentKey) => {
          if (currentKey && nextSummaries.some((summary) => scopeKey(summary) === currentKey)) {
            return currentKey;
          }
          return nextSummaries[0] ? scopeKey(nextSummaries[0]) : null;
        });
      })
      .catch((e) => {
        if (!cancelled) {
          console.error('Failed to load federal voting summary:', e);
          setSummaryError(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [politicianId, summaryRetryKey]);

  const selectedSummary = summaries?.find((summary) => scopeKey(summary) === selectedScopeKey)
    ?? summaries?.[0]
    ?? null;

  useEffect(() => {
    if (!selectedSummary) return;
    let cancelled = false;
    fetchFederalVotingAlignment(
      politicianId,
      selectedSummary.chamber,
      selectedSummary.congress,
    )
      .then((nextAlignment) => {
        if (!cancelled) {
          setAlignment(nextAlignment);
          setAlignmentError(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          console.error('Failed to load federal voting alignment:', e);
          setAlignmentError(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [alignmentRetryKey, politicianId, selectedSummary]);

  const selectScope = (nextKey: string) => {
    setSelectedScopeKey(nextKey);
    setAlignment(null);
    setAlignmentError(false);
    setSelectedPeerId(null);
    updateComparisonUrl(null);
  };

  const selectPeer = useCallback((peerId: string) => {
    setSelectedPeerId(peerId);
    updateComparisonUrl(peerId);
  }, []);

  if (!summaries && !summaryError) {
    return (
      <section className="animate-pulse space-y-4" aria-label="Loading official voting analytics">
        <div className="h-28 premium-card" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="h-28 premium-card" />
          <div className="h-28 premium-card" />
          <div className="h-28 premium-card" />
          <div className="h-28 premium-card" />
        </div>
      </section>
    );
  }

  if (summaryError && !summaries) {
    return (
      <section className="premium-card p-6 text-center" role="alert">
        <p className="font-semibold text-[var(--color-warning-badge)]">Could not load official federal voting analytics.</p>
        <button
          type="button"
          onClick={() => {
            setSummaryError(false);
            setSummaryRetryKey((value) => value + 1);
          }}
          className="mt-3 min-h-11 rounded-full border border-[var(--color-official-border)] px-4 text-sm font-bold text-[var(--color-official-link)] hover:border-[var(--color-official-link)] cursor-pointer"
        >
          Retry analytics
        </button>
      </section>
    );
  }

  if (!selectedSummary) {
    return (
      <section className="premium-card p-6">
        <p className="font-bold">Official federal voting analytics</p>
        <p className="mt-2 text-sm text-[var(--color-official-text-muted)]">
          No verified House or Senate roll-call window is available for this profile. State and historical voting records remain available below when present.
        </p>
      </section>
    );
  }

  const aligned = [...(alignment ?? [])]
    .filter((peer) => peer.aligned_rank <= 6)
    .sort((a, b) => a.aligned_rank - b.aligned_rank);
  const differing = [...(alignment ?? [])]
    .filter((peer) => peer.differ_count > 0 && peer.differing_rank <= 6)
    .sort((a, b) => a.differing_rank - b.differing_rank);
  const selectedPeer = alignment?.find((peer) => peer.peer_person_id === selectedPeerId) ?? null;

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-[var(--color-official-border)] bg-[var(--color-official-bg)] p-4 sm:p-6" aria-labelledby="official-voting-analytics-heading">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-[var(--color-official-border)] bg-[var(--color-official-bg-alt)] px-3 py-1 text-xs font-bold uppercase tracking-wider text-[var(--color-official-link)]">
                Official analytics
              </span>
              <span className="text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
                {selectedSummary.source_name}
              </span>
            </div>
            <h2 id="official-voting-analytics-heading" className="mt-3 text-2xl font-extrabold">Federal voting analytics</h2>
            <p className="mt-2 max-w-3xl text-sm text-[var(--color-official-text-muted)]">
              Coverage, participation, and peer comparisons come only from exact official roll calls tied to canonical people. These numbers describe recorded voting overlap, not political influence or endorsement.
            </p>
          </div>
          {summaries && summaries.length > 1 && (
            <label className="text-xs font-bold uppercase tracking-wider text-[var(--color-official-text-muted)]">
              Scope
              <select
                value={scopeKey(selectedSummary)}
                onChange={(event) => selectScope(event.target.value)}
                className="mt-2 block min-h-11 rounded-full border border-[var(--color-official-border)] bg-[var(--color-official-bg-alt)] px-4 text-sm normal-case tracking-normal text-[var(--color-official-text)] focus:border-[var(--color-official-link)] focus:outline-none"
              >
                {summaries.map((summary) => (
                  <option key={scopeKey(summary)} value={scopeKey(summary)}>
                    {chamberLabel(summary.chamber)} · Congress {summary.congress}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        <p className="mt-4 text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
          {chamberLabel(selectedSummary.chamber)} · Congress {selectedSummary.congress} · {formatDate(selectedSummary.first_vote_date)}–{formatDate(selectedSummary.last_vote_date)}
        </p>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard
            label="Covered official votes"
            value={selectedSummary.covered_vote_count.toLocaleString()}
            detail={`${selectedSummary.substantive_vote_count.toLocaleString()} Yea/Nay votes used for comparisons`}
          />
          <SummaryCard
            label="Participation"
            value={percentage(selectedSummary.participation_rate)}
            detail={`${selectedSummary.participating_vote_count.toLocaleString()} votes cast, including Present`}
          />
          <SummaryCard
            label="Yea / Nay"
            value={`${selectedSummary.yea_count.toLocaleString()} / ${selectedSummary.nay_count.toLocaleString()}`}
            detail="Recorded substantive positions in this covered window"
          />
          <SummaryCard
            label="Present / Not voting"
            value={`${selectedSummary.present_count.toLocaleString()} / ${selectedSummary.not_voting_count.toLocaleString()}`}
            detail="Shown for participation, excluded from alignment"
          />
        </div>
      </section>

      <section aria-labelledby="official-alignment-heading">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h3 id="official-alignment-heading" className="text-xl font-extrabold">Official voting alignment</h3>
            <p className="mt-1 max-w-3xl text-sm text-[var(--color-official-text-muted)]">
              Rankings require at least {selectedSummary.alignment_minimum_shared_votes} shared Yea/Nay votes in the same chamber and Congress. “Different” means opposite recorded votes on the same roll call.
            </p>
          </div>
          {selectedSummary.source_updated_at && (
            <span className="text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
              Observed {formatDate(selectedSummary.source_updated_at)}
            </span>
          )}
        </div>

        {!alignment && !alignmentError ? (
          <div className="mt-4 grid animate-pulse gap-4 md:grid-cols-2">
            <div className="h-40 premium-card" />
            <div className="h-40 premium-card" />
          </div>
        ) : alignmentError && !alignment ? (
          <div className="mt-4 premium-card p-6 text-center" role="alert">
            <p className="font-semibold text-[var(--color-warning-badge)]">Could not load official peer alignment.</p>
            <button
              type="button"
              onClick={() => {
                setAlignmentError(false);
                setAlignmentRetryKey((value) => value + 1);
              }}
              className="mt-3 min-h-11 rounded-full border border-[var(--color-official-border)] px-4 text-sm font-bold text-[var(--color-official-link)] hover:border-[var(--color-official-link)] cursor-pointer"
            >
              Retry alignment
            </button>
          </div>
        ) : aligned.length === 0 && differing.length === 0 ? (
          <div className="mt-4 premium-card p-6 text-center text-[var(--color-official-text-muted)]">
            No peers meet the minimum shared-vote sample in this scope yet.
          </div>
        ) : (
          <div className="mt-4 grid gap-6 lg:grid-cols-2">
            <div>
              <h4 className="mb-3 text-xs font-bold uppercase tracking-widest text-[var(--color-official-link)]">Most aligned</h4>
              <div className="space-y-3">
                {aligned.map((peer) => (
                  <PeerCard
                    key={`aligned-${peer.peer_person_id}`}
                    peer={peer}
                    rankKind="aligned"
                    selected={selectedPeerId === peer.peer_person_id}
                    onCompare={() => selectPeer(peer.peer_person_id)}
                  />
                ))}
              </div>
            </div>
            <div>
              <h4 className="mb-3 text-xs font-bold uppercase tracking-widest text-[var(--color-warning-badge)]">Most often differed</h4>
              <div className="space-y-3">
                {differing.map((peer) => (
                  <PeerCard
                    key={`differing-${peer.peer_person_id}`}
                    peer={peer}
                    rankKind="differing"
                    selected={selectedPeerId === peer.peer_person_id}
                    onCompare={() => selectPeer(peer.peer_person_id)}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </section>

      {selectedPeerId && selectedPeer && (
        <ComparisonPanel
          key={`${selectedPeerId}:${scopeKey(selectedSummary)}`}
          politicianId={politicianId}
          politicianName={politicianName}
          peer={selectedPeer}
          summary={selectedSummary}
          onClose={() => {
            setSelectedPeerId(null);
            updateComparisonUrl(null);
          }}
        />
      )}
    </div>
  );
}
