"use client";

import { useCallback, useEffect, useState } from 'react';
import { DEFAULT_PROFILE_PAGE_SIZE, emptyPage, type PageResult } from '@/lib/pagination';
import { fetchVotingRecords, type VotingRecord } from '@/lib/votingRecords';
import { EmptyState, formatDate, LoadingBlock, LoadError, PaginationControls, SectionHeading } from './ProfileSpokeStates';

const VOTE_FILTERS = ['', 'Yea', 'Nay', 'Present'];

export default function VotingRecordTab({ politicianId }: { politicianId: string }) {
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
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <SectionHeading title="Voting Record" meta={latest ? `Latest vote ${formatDate(latest)}` : undefined} />
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

      {!current.rows.length ? (
        <EmptyState>{voteCast ? `No ${voteCast} votes on record.` : 'No voting records available.'}</EmptyState>
      ) : (
        <>
          {current.rows.map((item) => (
            <div key={item.id} className="p-6 premium-card flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
              <div>
                <h3 className="font-bold text-xl mb-2 leading-tight">{item.bill_name}</h3>
                <p className="text-[var(--color-official-text-muted)] mb-3 text-sm md:text-base">{item.bill_summary || 'No bill summary available.'}</p>
                <div className="flex flex-wrap gap-3 text-xs font-mono uppercase text-[var(--color-official-text-muted)] tracking-widest">
                  <span>{formatDate(item.vote_date)}</span>
                  {item.jurisdiction && <span>{item.jurisdiction}</span>}
                </div>
              </div>
              <div className="shrink-0">
                <span className={`px-4 py-2 rounded-full font-bold text-sm tracking-widest uppercase border bg-[var(--color-official-bg-alt)] border-[var(--color-official-border)] ${
                  item.vote_cast === 'Yea' ? 'text-[var(--color-official-link)]' : 'text-[var(--color-warning-badge)]'
                }`}>
                  {item.vote_cast || 'Recorded'}
                </span>
              </div>
            </div>
          ))}
          {error && <p className="text-sm text-[var(--color-warning-badge)]">Could not refresh this page of voting records.</p>}
          <PaginationControls result={current} onPage={goToPage} />
        </>
      )}
    </div>
  );
}
