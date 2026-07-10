"use client";

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import PoliticianClient from '@/app/[politician_id]/PoliticianClient';
import { isCanonicalPoliticianRpcUnavailableError } from '@/lib/canonicalPoliticians';
import { isUuid } from '@/lib/ids';
import { fetchProfileHeader, type ProfileHeader } from '@/lib/profile';

export default function ProfilePageClient({ profileId }: { profileId?: string }) {
  if (typeof profileId === 'string') {
    return <ProfileById id={profileId} />;
  }

  return <ProfileFromSearchParams />;
}

function ProfileFromSearchParams() {
  const searchParams = useSearchParams();
  const id = searchParams.get('id') ?? '';

  return <ProfileById id={id} />;
}

function ProfileById({ id }: { id: string }) {
  if (!id) {
    return <ProfileUnavailable message="No politician was found for this live profile link." />;
  }

  if (!isUuid(id)) {
    return <ProfileUnavailable message="That profile link is not a valid database id." />;
  }

  return <LiveProfile key={id} id={id} />;
}

function LiveProfile({ id }: { id: string }) {
  const [politician, setPolitician] = useState<ProfileHeader | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchProfileHeader(id)
      .then((nextPolitician) => {
        if (cancelled) return;
        if (nextPolitician) {
          setPolitician(nextPolitician);
        } else {
          setError('No politician was found for this live profile link.');
        }
      })
      .catch((e) => {
        if (!cancelled) {
          console.error('Failed to load live profile:', e);
          setError(
            isCanonicalPoliticianRpcUnavailableError(e)
              ? 'Canonical profile data is temporarily unavailable. To avoid showing a duplicate or incomplete record, this profile is paused.'
              : 'Could not load this live profile. Please try again later.'
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (!error && !politician) {
    return (
      <main className="min-h-screen bg-[var(--color-official-bg)] text-[var(--color-official-text)] p-4">
        <div className="max-w-6xl mx-auto py-12 space-y-6">
          <div className="h-8 w-48 rounded bg-[var(--color-official-border)] animate-pulse" />
          <div className="h-64 rounded-2xl bg-[var(--color-official-bg-alt)] border border-[var(--color-official-border)] animate-pulse" />
          <div className="h-48 rounded-2xl bg-[var(--color-official-bg-alt)] border border-[var(--color-official-border)] animate-pulse" />
        </div>
      </main>
    );
  }

  if (error || !politician) {
    return <ProfileUnavailable message={error || 'No politician was found for this live profile link.'} />;
  }

  return <PoliticianClient politician={politician} />;
}

function ProfileUnavailable({ message }: { message: string }) {
  return (
    <main className="min-h-screen bg-[var(--color-official-bg)] text-[var(--color-official-text)] p-4">
      <div className="max-w-2xl mx-auto py-16">
        <Link href="/" className="text-[var(--color-official-link)] hover:underline font-bold">
          &larr; Back to Search
        </Link>
        <div className="premium-card p-8 mt-8 text-center">
          <h1 className="text-2xl font-bold mb-3">Profile unavailable</h1>
          <p className="text-[var(--color-official-text-muted)]">{message}</p>
        </div>
      </div>
    </main>
  );
}
