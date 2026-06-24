import { Suspense } from 'react';
import type { Metadata } from 'next';
import ProfilePageClient from './ProfilePageClient';

export const metadata: Metadata = {
  title: 'Live Profile | Avanguardia Publica',
  description: 'Live Supabase-backed politician profile.',
};

export default function ProfilePage() {
  return (
    <Suspense fallback={<ProfileLoading />}>
      <ProfilePageClient />
    </Suspense>
  );
}

function ProfileLoading() {
  return (
    <main className="min-h-screen bg-[var(--color-official-bg)] text-[var(--color-official-text)] p-4">
      <div className="max-w-6xl mx-auto py-12 space-y-6">
        <div className="h-8 w-48 rounded bg-[var(--color-official-border)] animate-pulse" />
        <div className="h-64 rounded-2xl bg-[var(--color-official-bg-alt)] border border-[var(--color-official-border)] animate-pulse" />
      </div>
    </main>
  );
}
