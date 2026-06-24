"use client";

import { useCallback, useEffect, useState } from 'react';
import { fetchMediaMentions, type MediaMention } from '@/lib/mediaMentions';
import { DEFAULT_PROFILE_PAGE_SIZE, emptyPage, type PageResult } from '@/lib/pagination';
import { EmptyState, formatDateTime, LoadingBlock, LoadError, PaginationControls } from './ProfileSpokeStates';

export default function MediaMentionsTab({ politicianId }: { politicianId: string }) {
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<PageResult<MediaMention> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchPage = useCallback(
    () => fetchMediaMentions(politicianId, page, DEFAULT_PROFILE_PAGE_SIZE),
    [page, politicianId],
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    fetchPage()
      .then(setResult)
      .catch((e) => {
        console.error('Failed to load media mentions:', e);
        setError(true);
      })
      .finally(() => setLoading(false));
  }, [fetchPage]);

  useEffect(() => {
    let cancelled = false;
    fetchPage()
      .then((nextResult) => {
        if (!cancelled) setResult(nextResult);
      })
      .catch((e) => {
        if (!cancelled) {
          console.error('Failed to load media mentions:', e);
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
  };

  if (loading && !result) return <LoadingBlock />;
  if (error && !result) return <LoadError message="Could not load media mentions." onRetry={load} />;

  const current = result ?? emptyPage<MediaMention>(page);

  return (
    <div className="visual-firewall">
      <div className="mb-8">
        <span className="warning-badge">Third-Party Data - Unverified</span>
        <p className="text-sm opacity-80 mt-2 max-w-3xl">
          The following information is ingested automatically from third-party APIs based on name matching. It has not been verified against official government records.
        </p>
      </div>

      {!current.rows.length ? (
        <EmptyState>No unconfirmed mentions found.</EmptyState>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {current.rows.map((item) => (
              <div key={item.id} className="p-5 bg-[var(--color-official-bg)] border border-[var(--color-official-border)] rounded-xl shadow-sm hover:shadow-md transition-shadow">
                <div className="flex justify-between items-start gap-3 mb-3">
                  <span className="text-xs font-bold text-[var(--color-official-text-muted)] uppercase tracking-widest bg-[var(--color-official-bg-alt)] px-2 py-1 rounded">
                    {item.source_api}
                  </span>
                  {item.sentiment_score !== null && (
                    <span className="text-xs font-mono text-[var(--color-official-text-muted)]">Sentiment: {item.sentiment_score}</span>
                  )}
                </div>
                <p className="mb-4 text-sm leading-relaxed">{item.content_summary}</p>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-xs text-[var(--color-official-text-muted)]">Ingested {formatDateTime(item.created_at)}</span>
                  {item.url && (
                    <a href={item.url} target="_blank" rel="noreferrer" className="text-[var(--color-official-link)] hover:underline text-xs font-bold uppercase tracking-wider inline-flex items-center">
                      Source Link <span className="ml-1">&rarr;</span>
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
          {error && <p className="mt-3 text-sm text-[var(--color-warning-badge)]">Could not refresh this page of media mentions.</p>}
          <PaginationControls result={current} onPage={goToPage} />
        </>
      )}
    </div>
  );
}
