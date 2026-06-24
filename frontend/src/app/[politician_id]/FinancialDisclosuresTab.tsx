"use client";

import { useCallback, useEffect, useState } from 'react';
import { fetchFinancialDisclosures, type FinancialDisclosure } from '@/lib/financialDisclosures';
import { DEFAULT_PROFILE_PAGE_SIZE, emptyPage, type PageResult } from '@/lib/pagination';
import { EmptyState, formatDate, LoadingBlock, LoadError, PaginationControls, SectionHeading } from './ProfileSpokeStates';

export default function FinancialDisclosuresTab({ politicianId }: { politicianId: string }) {
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<PageResult<FinancialDisclosure> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchPage = useCallback(
    () => fetchFinancialDisclosures(politicianId, page, DEFAULT_PROFILE_PAGE_SIZE),
    [page, politicianId],
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    fetchPage()
      .then(setResult)
      .catch((e) => {
        console.error('Failed to load financial disclosures:', e);
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
          console.error('Failed to load financial disclosures:', e);
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
  if (error && !result) return <LoadError message="Could not load financial disclosures." onRetry={load} />;

  const current = result ?? emptyPage<FinancialDisclosure>(page);
  const latest = current.rows[0]?.filing_date;

  if (!current.rows.length) {
    return <EmptyState>No financial disclosures on record.</EmptyState>;
  }

  return (
    <div className="premium-card p-4">
      <SectionHeading
        title="Financial Disclosures"
        meta={latest ? `Latest filing ${formatDate(latest)}` : undefined}
      />
      <p className="pb-4 text-sm text-[var(--color-official-text-muted)]">
        Official filing-level records from the U.S. House Clerk. Open a filing to view its itemized transactions and asset values.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] text-left border-collapse">
          <thead>
            <tr className="bg-[var(--color-official-bg-alt)] border-b border-[var(--color-official-border)]">
              <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Filed</th>
              <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Filing Type</th>
              <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Document</th>
            </tr>
          </thead>
          <tbody>
            {current.rows.map((item) => (
              <tr key={item.id} className="border-b border-[var(--color-official-border)] last:border-b-0 hover:bg-[var(--color-official-bg-alt)]/50 transition-colors">
                <td className="p-4 whitespace-nowrap text-sm">{formatDate(item.filing_date)}</td>
                <td className="p-4 font-medium">{item.filing_type || 'Disclosure filing'}</td>
                <td className="p-4">
                  {item.doc_url ? (
                    <a href={item.doc_url} target="_blank" rel="noreferrer" className="text-[var(--color-official-link)] hover:underline text-sm font-bold inline-flex items-center">
                      View filing <span className="ml-1">&rarr;</span>
                    </a>
                  ) : (
                    <span className="text-[var(--color-official-text-muted)]">N/A</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <p className="mt-3 text-sm text-[var(--color-warning-badge)]">Could not refresh this page of disclosures.</p>}
      <PaginationControls result={current} onPage={goToPage} />
    </div>
  );
}
