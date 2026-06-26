"use client";

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { fetchPoliticianSummaries, searchPoliticians, type PoliticianSummary } from '@/lib/politicians';
import { profilePath } from '@/lib/routes';

type Politician = PoliticianSummary;

export default function Home() {
  const [search, setSearch] = useState("");
  const [featured, setFeatured] = useState<Politician[]>([]);
  const [searchResults, setSearchResults] = useState<Politician[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchLoading, setSearchLoading] = useState(false);

  useEffect(() => {
    async function fetchFeatured() {
      // Mock fallback if supabase isn't connected
      const mockData: Politician[] = [
        { id: 'biden-joe', full_name: 'Joe Biden', current_office: 'President of the United States', party: 'Democratic', state: null, district: null },
        { id: 'harris-kamala', full_name: 'Kamala Harris', current_office: 'Vice President of the United States', party: 'Democratic', state: null, district: null },
      ];
      
      try {
        if (!process.env.NEXT_PUBLIC_SUPABASE_URL) throw new Error("No URL");
        const data = await fetchPoliticianSummaries(6);
        setFeatured(data);
      } catch (e) {
        console.warn("Falling back to mock data. Supabase connection failed:", e);
        setFeatured(mockData);
      } finally {
        setLoading(false);
      }
    }
    fetchFeatured();
  }, []);

  useEffect(() => {
    const trimmed = search.trim();
    if (!trimmed) {
      return;
    }

    let cancelled = false;
    const timeout = window.setTimeout(() => {
      setSearchLoading(true);
      searchPoliticians(trimmed)
        .then((results) => {
          if (!cancelled) setSearchResults(results);
        })
        .catch((e) => {
          console.warn("Supabase search failed:", e);
          if (!cancelled) {
            const fallback = featured.filter((p) =>
              p.full_name.toLowerCase().includes(trimmed.toLowerCase())
            );
            setSearchResults(fallback);
          }
        })
        .finally(() => {
          if (!cancelled) setSearchLoading(false);
        });
    }, 200);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [featured, search]);

  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-4">
      <div className="absolute inset-0 z-[-1] bg-gradient-to-b from-[var(--color-official-bg)] to-[var(--color-official-bg-alt)] dark:from-[#0b0f19] dark:to-[#111827]" />
      
      <div className="max-w-2xl w-full text-center space-y-10">
        <div className="space-y-4">
          <h1 className="text-5xl md:text-6xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-500 dark:from-blue-400 dark:to-indigo-300">
            Avanguardia Publica
          </h1>
          <p className="text-xl text-[var(--color-official-text-muted)] font-light">
            The unvarnished public record index.
          </p>
        </div>

        <div className="relative premium-card p-2 md:p-4 bg-[var(--color-official-bg)]/80 backdrop-blur-md">
          <input 
            type="text" 
            placeholder="Search politicians by name..." 
            className="w-full p-4 bg-transparent border-b-2 border-transparent focus:border-[var(--color-official-link)] text-xl focus:outline-none transition-colors dark:text-white"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          
          {search && (
            <div className="absolute left-0 right-0 mt-4 bg-[var(--color-official-bg)] border border-[var(--color-official-border)] rounded-xl shadow-2xl text-left overflow-hidden z-20">
              {searchLoading ? (
                <div className="p-6 text-center text-[var(--color-official-text-muted)]">Searching...</div>
              ) : searchResults.length > 0 ? (
                searchResults.map(p => (
                  <Link href={profilePath(p.id)} key={p.id} className="block p-4 hover:bg-[var(--color-official-bg-alt)] border-b border-[var(--color-official-border)] last:border-0 transition-colors">
                    <div className="font-bold text-lg">{p.full_name}</div>
                    <div className="text-sm text-[var(--color-official-text-muted)]">{p.current_office}</div>
                  </Link>
                ))
              ) : (
                <div className="p-6 text-center text-[var(--color-official-text-muted)]">No results found</div>
              )}
            </div>
          )}
        </div>

        <div className="pt-12 text-left">
          <div className="flex justify-between items-center mb-6 ml-2">
            <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--color-official-text-muted)]">Browse Directory</h2>
            <Link
              href="/directory"
              className="text-sm font-bold text-[var(--color-official-link)] hover:underline inline-flex items-center gap-1 transition-colors"
            >
              View All Categories &rarr;
            </Link>
          </div>
          {loading ? (
            <div className="animate-pulse flex space-x-4">
              <div className="flex-1 space-y-4 py-1">
                <div className="h-4 bg-[var(--color-official-border)] rounded w-3/4"></div>
                <div className="h-4 bg-[var(--color-official-border)] rounded w-1/2"></div>
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {featured.map(p => (
                  <Link href={profilePath(p.id)} key={p.id} className="premium-card p-5 group flex flex-col h-full bg-[var(--color-official-bg)]">
                    <div className="font-bold text-lg group-hover:text-[var(--color-official-link)] transition-colors mb-1">{p.full_name}</div>
                    <div className="text-sm text-[var(--color-official-text-muted)] flex-grow">{p.current_office}</div>
                    <div className="text-xs font-mono mt-4 text-[var(--color-official-text-muted)] uppercase">{p.party}</div>
                  </Link>
                ))}
              </div>
              <div className="mt-6 text-center">
                <Link
                  href="/directory"
                  className="inline-flex items-center gap-2 px-6 py-3 rounded-full border border-[var(--color-official-border)] text-sm font-bold text-[var(--color-official-text-muted)] hover:text-[var(--color-official-link)] hover:border-[var(--color-official-link)] transition-all"
                >
                  View Full Directory by Category
                  <span className="text-[var(--color-official-link)]">&rarr;</span>
                </Link>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
