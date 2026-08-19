"use client";

import { useCallback, useEffect, useState } from 'react';
import { DEFAULT_PROFILE_PAGE_SIZE, emptyPage, type PageResult } from '@/lib/pagination';
import {
  fetchVotingRecords,
  type LegislativeMeasure,
  type LegislativeMeasureType,
  type VotingRecord,
} from '@/lib/votingRecords';
import { EmptyState, formatDate, LoadingBlock, LoadError, PaginationControls, SectionHeading } from './ProfileSpokeStates';
import VotingAnalyticsPanel from './VotingAnalyticsPanel';

const VOTE_FILTERS = ['', 'Yea', 'Nay', 'Present', 'Not Voting'];

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

function chamberLabel(chamber: VotingRecord['chamber']): string | null {
  if (chamber === 'house') return 'U.S. House';
  if (chamber === 'senate') return 'U.S. Senate';
  return null;
}

function voteBadgeClass(voteCast: string | null): string {
  if (voteCast === 'Yea') return 'text-[var(--color-official-link)]';
  if (voteCast === 'Nay') return 'text-[var(--color-warning-badge)]';
  return 'text-[var(--color-official-text-muted)]';
}

function measureLabel(measure: LegislativeMeasure): string {
  return `${MEASURE_TYPE_LABELS[measure.measure_type]} ${measure.measure_number}`;
}

export default function VotingRecordTab({
  politicianId,
  politicianName,
}: {
  politicianId: string;
  politicianName: string;
}) {
  return (
    <div className="space-y-10">
      <VotingAnalyticsPanel politicianId={politicianId} politicianName={politicianName} />
      <VotingRecordsList politicianId={politicianId} />
    </div>
  );
}

function VotingRecordsList({ politicianId }: { politicianId: string }) {
  const [page, setPage] = useState(0);
  const [voteCast, setVoteCast] = useState('');
  const [result, setResult] = useState<PageResult<VotingRecord> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchPage = useCallback(
    () => fetchVotingRecords(politicianId, page, DEFAULT_PROFILE_PAGE_SIZE, { voteCast }),
    [page, politicianId, voteCast],
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    fetchPage()
      .then(setResult)
      .catch((e) => {
        console.error('Failed to load voting records:', e);
        setError(true);
      })
      .finally(() => setLoading(false));
  }, [fetchPage]);

  useEffect(() => {
    let cancelled = false;
    fetchPage()
      .then((nextResult) => {
        if (!cancelled) {
          setError(false);
          setResult(nextResult);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          console.error('Failed to load voting records:', e);
          setError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [fetchPage]);

  const goToPage = (nextPage: number) => {
    setPage(nextPage);
    setResult(null);
    setLoading(true);
    setError(false);
  };

  const changeFilter = (next: string) => {
    setVoteCast(next);
    setPage(0);
    setResult(null);
    setLoading(true);
    setError(false);
  };

  if (loading && !result) return <LoadingBlock />;
  if (error && !result) return <LoadError message="Could not load voting records." onRetry={load} />;

  const current = result ?? emptyPage<VotingRecord>(page);
  const latest = current.rows[0]?.vote_date;

  return (
    <section className="space-y-4" aria-labelledby="voting-record-heading">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div id="voting-record-heading">
          <SectionHeading title="Voting Record" meta={latest ? `Latest vote ${formatDate(latest)}` : undefined} />
        </div>
        <label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[var(--color-official-text-muted)]">
          Vote
          <select
            value={voteCast}
            onChange={(e) => changeFilter(e.target.value)}
            className="min-h-11 rounded-full border border-[var(--color-official-border)] bg-[var(--color-official-bg)] px-3 text-sm normal-case tracking-normal text-[var(--color-official-text)] focus:border-[var(--color-official-link)] focus:outline-none"
          >
            {VOTE_FILTERS.map((filter) => (
              <option key={filter || 'all'} value={filter}>
                {filter || 'All votes'}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="text-sm text-[var(--color-official-text-muted)]">
        Federal records marked Official come directly from the U.S. House Clerk or U.S. Senate.
        {' '}State and historical coverage may use the existing vote feeds.
      </p>

      {!current.rows.length ? (
        <EmptyState>{voteCast ? `No ${voteCast} votes on record.` : 'No voting records available.'}</EmptyState>
      ) : (
        <>
          {current.rows.map((item) => {
            const chamber = chamberLabel(item.chamber);
            const sourceMeta = [
              chamber,
              item.congress ? `Congress ${item.congress}` : null,
              item.session ? `Session ${item.session}` : null,
              item.roll_call_number ? `Roll call ${item.roll_call_number}` : null,
            ].filter(Boolean);

            return (
              <article key={item.id} className="p-6 premium-card flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                <div>
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    {item.record_origin === 'official' && (
                      <span className="rounded-full border border-[var(--color-official-border)] bg-[var(--color-official-bg-alt)] px-3 py-1 text-xs font-bold uppercase tracking-wider text-[var(--color-official-link)]">
                        Official
                      </span>
                    )}
                    {sourceMeta.map((value) => (
                      <span key={value} className="text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
                        {value}
                      </span>
                    ))}
                  </div>
                  <h3 className="font-bold text-xl mb-2 leading-tight">{item.bill_name}</h3>
                  <p className="text-[var(--color-official-text-muted)] mb-3 text-sm md:text-base">
                    {item.vote_result
                      ? `Result: ${item.vote_result}`
                      : item.bill_summary || 'No vote summary available.'}
                  </p>
                  {item.measures.length > 0 && (
                    <div className="mb-4 space-y-2">
                      {item.measures.map((measure) => (
                        <div
                          key={measure.canonical_measure_key}
                          className="rounded-xl border border-[var(--color-official-border)] bg-[var(--color-official-bg-alt)] p-3"
                        >
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
                            <span className="font-bold text-[var(--color-official-link)]">
                              {measure.measure_kind === 'bill' ? 'Official bill' : 'Official amendment'}
                            </span>
                            <span>{measureLabel(measure)}</span>
                            <span>Congress {measure.congress}</span>
                            {measure.official_url ? (
                              <a
                                href={measure.official_url}
                                target="_blank"
                                rel="noreferrer"
                                className="font-bold text-[var(--color-official-link)] hover:underline"
                              >
                                View on Congress.gov
                              </a>
                            ) : (
                              <span>{measure.source_name || 'Congress.gov'}</span>
                            )}
                          </div>
                          {measure.title && (
                            <p className="mt-2 text-sm font-semibold text-[var(--color-official-text)]">
                              {measure.title}
                            </p>
                          )}
                          {measure.purpose && measure.purpose !== measure.title && (
                            <p className="mt-1 text-sm text-[var(--color-official-text-muted)]">
                              Purpose: {measure.purpose}
                            </p>
                          )}
                          {measure.observed_at && (
                            <p className="mt-2 text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
                              Observed {formatDate(measure.observed_at)}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs font-mono uppercase text-[var(--color-official-text-muted)] tracking-widest">
                    <span>{formatDate(item.vote_date)}</span>
                    {item.jurisdiction && <span>{item.jurisdiction}</span>}
                    {item.source_updated_at && <span>Observed {formatDate(item.source_updated_at)}</span>}
                    {item.source_url ? (
                      <a
                        href={item.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-bold text-[var(--color-official-link)] hover:underline"
                      >
                        Source: {item.source_name || 'Official record'}
                      </a>
                    ) : item.source_name ? (
                      <span>Source: {item.source_name}</span>
                    ) : null}
                  </div>
                </div>
                <div className="shrink-0">
                  <span className={`px-4 py-2 rounded-full font-bold text-sm tracking-widest uppercase border bg-[var(--color-official-bg-alt)] border-[var(--color-official-border)] ${voteBadgeClass(item.vote_cast)}`}>
                    {item.vote_cast || 'Recorded'}
                  </span>
                </div>
              </article>
            );
          })}
          {error && <p className="text-sm text-[var(--color-warning-badge)]">Could not refresh this page of voting records.</p>}
          <PaginationControls result={current} onPage={goToPage} />
        </>
      )}
    </section>
  );
}
