"use client";

import { useCallback, useEffect, useState } from 'react';
import { isUuid } from '@/lib/ids';
import { fetchContactInfo, type ContactInfo } from '@/lib/profile';
import { formatDateTime, LoadError } from './ProfileSpokeStates';

export default function OfficialContactCard({
  politicianId,
  initialContact,
}: {
  politicianId: string;
  initialContact?: ContactInfo | null;
}) {
  const hasLiveProfileId = isUuid(politicianId);
  const [contact, setContact] = useState<ContactInfo | null>(initialContact ?? null);
  const [loading, setLoading] = useState(hasLiveProfileId);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    if (!hasLiveProfileId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(false);
    fetchContactInfo(politicianId)
      .then(setContact)
      .catch((e) => {
        console.error('Failed to load contact info:', e);
        setError(true);
      })
      .finally(() => setLoading(false));
  }, [hasLiveProfileId, politicianId]);

  useEffect(() => {
    if (!hasLiveProfileId) return;
    let cancelled = false;

    fetchContactInfo(politicianId)
      .then((nextContact) => {
        if (!cancelled) setContact(nextContact);
      })
      .catch((e) => {
        if (!cancelled) {
          console.error('Failed to load contact info:', e);
          setError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [hasLiveProfileId, politicianId]);

  if (loading) {
    return (
      <div className="mt-8 p-6 premium-card max-w-2xl animate-pulse">
        <div className="h-4 w-36 rounded bg-[var(--color-official-border)] mb-5" />
        <div className="space-y-3">
          <div className="h-4 w-5/6 rounded bg-[var(--color-official-border)]" />
          <div className="h-4 w-2/3 rounded bg-[var(--color-official-border)]" />
          <div className="h-4 w-4/5 rounded bg-[var(--color-official-border)]" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mt-8 max-w-2xl">
        <LoadError message="Could not load official contact information." onRetry={load} />
      </div>
    );
  }

  return (
    <div className="mt-8 p-6 premium-card max-w-2xl">
      <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-text-muted)]">Official Contact</h2>
        <p className="text-xs text-[var(--color-official-text-muted)]">Updated {formatDateTime(contact?.last_updated)}</p>
      </div>
      <div className="space-y-3 text-sm md:text-base">
        <p><strong className="font-semibold text-[var(--color-official-text-muted)] mr-2">Address:</strong> {contact?.office_address || 'N/A'}</p>
        <p><strong className="font-semibold text-[var(--color-official-text-muted)] mr-2">Phone:</strong> {contact?.phone_number || 'N/A'}</p>
        <p>
          <strong className="font-semibold text-[var(--color-official-text-muted)] mr-2">Website:</strong>
          {contact?.official_website ? (
            <a href={contact.official_website} className="text-[var(--color-official-link)] hover:underline ml-1 break-all" target="_blank" rel="noreferrer">{contact.official_website}</a>
          ) : 'N/A'}
        </p>
      </div>
    </div>
  );
}
