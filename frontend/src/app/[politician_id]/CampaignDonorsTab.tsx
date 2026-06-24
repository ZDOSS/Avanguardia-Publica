"use client";

import { useCallback, useEffect, useState } from 'react';
import { fetchCampaignDonors, type CampaignDonor } from '@/lib/campaignDonors';
import { DEFAULT_PROFILE_PAGE_SIZE, emptyPage, type PageResult } from '@/lib/pagination';
import { EmptyState, formatDate, LoadingBlock, LoadError, PaginationControls, SectionHeading } from './ProfileSpokeStates';

const currency = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

export default function CampaignDonorsTab({ politicianId }: { politicianId: string }) {
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<PageResult<CampaignDonor> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchPage = useCallback(
    () => fetchCampaignDonors(politicianId, page, DEFAULT_PROFILE_PAGE_SIZE),
    [page, politicianId],
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    fetchPage()
      .then(setResult)
      .catch((e) => {
        console.error('Failed to load campaign donors:', e);
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
          console.error('Failed to load campaign donors:', e);
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

  if (loading && !result) return <LoadingBlock />;
  if (error && !result) return <LoadError message="Could not load campaign donors." onRetry={load} />;

  const current = result ?? emptyPage<CampaignDonor>(page);
  const latest = current.rows.find((row) => row.donation_date)?.donation_date;

  if (!current.rows.length) {
    return <EmptyState>No campaign donors on record.</EmptyState>;
  }

  return (
    <div className="premium-card p-4">
      <SectionHeading
        title="Campaign Donors"
        meta={latest ? `Latest donation ${formatDate(latest)}` : undefined}
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] text-left border-collapse">
          <thead>
            <tr className="bg-[var(--color-official-bg-alt)] border-b border-[var(--color-official-border)]">
              <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Date</th>
              <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Donor Name</th>
              <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Type</th>
              <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Amount</th>
            </tr>
          </thead>
          <tbody>
            {current.rows.map((item) => (
              <tr key={item.id} className="border-b border-[var(--color-official-border)] last:border-b-0 hover:bg-[var(--color-official-bg-alt)]/50 transition-colors">
                <td className="p-4 whitespace-nowrap text-sm">{formatDate(item.donation_date)}</td>
                <td className="p-4 font-medium">{item.donor_name}</td>
                <td className="p-4">
                  <span className={`px-2 py-1 bg-[var(--color-official-bg-alt)] border border-[var(--color-official-border)] rounded text-xs font-bold uppercase tracking-wider ${
                    item.pac_status ? 'text-[var(--color-official-text-muted)]' : 'text-[var(--color-official-link)]'
                  }`}>
                    {item.pac_status ? 'PAC' : 'Individual'}
                  </span>
                </td>
                <td className="p-4 font-mono font-bold">{currency.format(item.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <p className="mt-3 text-sm text-[var(--color-warning-badge)]">Could not refresh this page of donors.</p>}
      <PaginationControls result={current} onPage={goToPage} />
    </div>
  );
}
