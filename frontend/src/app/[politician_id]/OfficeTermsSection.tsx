"use client";

import { useCallback, useEffect, useState } from 'react';
import { isCanonicalPoliticianRpcUnavailableError } from '@/lib/canonicalPoliticians';
import { isUuid } from '@/lib/ids';
import { fetchPersonOfficeTerms, type PersonOfficeTerm } from '@/lib/officeTerms';
import { safeHttpUrl } from '@/lib/urls';

const VERIFICATION_LABELS: Record<string, string> = {
  verified: 'Verified source record',
  unverified: 'Unverified source record',
  mixed: 'Mixed verification',
  unknown: 'Verification unknown',
};

function displayKey(value: string): string {
  return value
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatTermDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
}

function termPeriod(term: PersonOfficeTerm): string {
  const start = formatTermDate(term.term_start);
  const end = formatTermDate(term.term_end);
  if (!start && !end) return term.term_status === 'current' ? 'Current term' : 'Dates unavailable';
  return `${start ?? 'Start unavailable'} – ${end ?? (term.term_status === 'current' ? 'Present' : 'End unavailable')}`;
}

function termLocation(term: PersonOfficeTerm): string {
  const seen = new Set<string>();
  return [term.jurisdiction, term.state, term.district ? `District ${term.district}` : null]
    .filter((value): value is string => {
      if (!value) return false;
      const key = value.trim().toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .join(' · ');
}

function OfficeTermCard({ term }: { term: PersonOfficeTerm }) {
  const sourceUrl = safeHttpUrl(term.source_url);
  const verification = VERIFICATION_LABELS[term.verified_lane] ?? displayKey(term.verified_lane || 'unknown');
  const isVerified = term.verified_lane === 'verified';
  const location = termLocation(term);

  return (
    <article className="rounded-xl border border-[var(--color-official-border)] bg-[var(--color-official-bg)] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="font-bold text-[var(--color-official-text)]">{term.office_title}</h3>
          {term.organization_name && (
            <p className="mt-1 text-sm text-[var(--color-official-text-muted)]">{term.organization_name}</p>
          )}
          {location && <p className="mt-1 text-xs text-[var(--color-official-text-muted)]">{location}</p>}
        </div>
        <span className="shrink-0 rounded-full border border-[var(--color-official-border)] bg-[var(--color-official-bg-alt)] px-3 py-1 text-xs font-bold uppercase tracking-wider text-[var(--color-official-text-muted)]">
          {displayKey(term.term_status)}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[var(--color-official-text-muted)]">
        <span>{termPeriod(term)}</span>
        <span className={isVerified ? 'text-[var(--color-official-link)]' : 'text-[var(--color-warning-badge)]'}>
          {verification}
        </span>
        {sourceUrl ? (
          <a href={sourceUrl} target="_blank" rel="noreferrer" className="font-semibold text-[var(--color-official-link)] hover:underline">
            Source: {displayKey(term.source_system_key)}
          </a>
        ) : (
          <span>Source: {displayKey(term.source_system_key)}</span>
        )}
      </div>
    </article>
  );
}

export default function OfficeTermsSection({ politicianId }: { politicianId: string }) {
  const hasLiveProfileId = isUuid(politicianId);
  const [terms, setTerms] = useState<PersonOfficeTerm[] | null>(hasLiveProfileId ? null : []);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    if (!hasLiveProfileId) return;
    setError(null);
    setTerms(null);
    fetchPersonOfficeTerms(politicianId)
      .then(setTerms)
      .catch((nextError) => setError(nextError));
  }, [hasLiveProfileId, politicianId]);

  useEffect(() => {
    if (!hasLiveProfileId) return;
    let cancelled = false;

    fetchPersonOfficeTerms(politicianId)
      .then((nextTerms) => {
        if (!cancelled) setTerms(nextTerms);
      })
      .catch((nextError) => {
        if (!cancelled) setError(nextError);
      });

    return () => {
      cancelled = true;
    };
  }, [hasLiveProfileId, politicianId]);

  if (!hasLiveProfileId) return null;

  if (error) {
    const message = isCanonicalPoliticianRpcUnavailableError(error)
      ? 'Canonical office history is temporarily unavailable. Legacy office rows are hidden to avoid mixing identities.'
      : 'Could not load office history. Please try again later.';
    return (
      <section className="premium-card mb-8 p-5" aria-labelledby="office-history-heading" role="status">
        <h2 id="office-history-heading" className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-text-muted)]">Public Offices</h2>
        <p className="mt-3 text-sm text-[var(--color-warning-badge)]">{message}</p>
        <button
          type="button"
          onClick={load}
          className="mt-3 min-h-11 rounded-full border border-[var(--color-official-border)] px-4 text-sm font-bold text-[var(--color-official-link)] transition-colors hover:border-[var(--color-official-link)] cursor-pointer"
        >
          Retry
        </button>
      </section>
    );
  }

  if (terms === null) {
    return (
      <section className="premium-card mb-8 p-5 animate-pulse" aria-label="Loading public offices">
        <div className="h-4 w-32 rounded bg-[var(--color-official-border)]" />
        <div className="mt-4 h-20 rounded-xl bg-[var(--color-official-bg-alt)]" />
      </section>
    );
  }

  if (!terms.length) return null;

  return (
    <section className="premium-card mb-8 p-5" aria-labelledby="office-history-heading">
      <div className="mb-4">
        <h2 id="office-history-heading" className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-text-muted)]">Public Offices</h2>
        <p className="mt-1 text-sm text-[var(--color-official-text-muted)]">Current and prior roles, kept separate from person identity.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {terms.map((term) => <OfficeTermCard key={term.id} term={term} />)}
      </div>
    </section>
  );
}
