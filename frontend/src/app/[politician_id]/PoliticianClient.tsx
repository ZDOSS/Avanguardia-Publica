"use client";

import { useState } from 'react';
import Link from 'next/link';
import CampaignDonorsTab from './CampaignDonorsTab';
import ConnectionsTab from './ConnectionsTab';
import FinancialDisclosuresTab from './FinancialDisclosuresTab';
import MediaMentionsTab from './MediaMentionsTab';
import OfficialContactCard from './OfficialContactCard';
import { formatDateTime } from './ProfileSpokeStates';
import VotingRecordTab from './VotingRecordTab';
import type { ContactInfo, ProfileHeader } from '@/lib/profile';

type TabId = 'financial' | 'donors' | 'votes' | 'connections' | 'media';

export interface PoliticianData extends ProfileHeader {
  contact_info?: ContactInfo[];
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'financial', label: 'Financial Disclosures' },
  { id: 'donors', label: 'Campaign Donors' },
  { id: 'votes', label: 'Voting Record' },
  { id: 'connections', label: 'Connections' },
  { id: 'media', label: 'Media' },
];

function normalizeTab(value: string | null): TabId {
  if (value === 'voting') return 'votes';
  return TABS.some((tab) => tab.id === value) ? (value as TabId) : 'financial';
}

export default function PoliticianClient({ politician }: { politician: PoliticianData }) {
  const [activeTab, setActiveTab] = useState<TabId>(() => {
    if (typeof window === 'undefined') return 'financial';
    return normalizeTab(new URLSearchParams(window.location.search).get('tab'));
  });

  const selectTab = (tab: TabId) => {
    setActiveTab(tab);
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (tab === 'financial') {
      url.searchParams.delete('tab');
    } else {
      url.searchParams.set('tab', tab);
    }
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  };

  const initialContact = politician.contact_info?.[0] ?? null;
  const office = politician.current_office || 'Office unavailable';
  const party = politician.party || 'Party unavailable';

  return (
    <div className="min-h-screen bg-[var(--color-official-bg)] text-[var(--color-official-text)] transition-colors">
      <nav className="glass-header sticky top-0 z-50 p-4">
        <div className="max-w-6xl mx-auto flex justify-between items-center gap-4">
          <Link href="/" className="text-[var(--color-official-link)] hover:underline font-bold transition-all hover:tracking-wide">
            &larr; Back to Search
          </Link>
          <span className="text-[var(--color-official-text-muted)] font-mono text-sm uppercase tracking-widest">Avanguardia Publica</span>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto p-4 py-8 md:py-12">
        <div className="flex flex-col md:flex-row gap-8 mb-12">
          <div className="w-48 h-64 bg-[var(--color-official-bg-alt)] border border-[var(--color-official-border)] flex items-center justify-center rounded-2xl shadow-sm shrink-0">
            <span className="text-[var(--color-official-text-muted)] text-sm uppercase tracking-widest">Portrait</span>
          </div>

          <div className="flex flex-col justify-between w-full">
            <div>
              <h1 className="text-4xl md:text-5xl font-extrabold mb-2 text-[var(--color-official-text)]">
                {politician.full_name}
              </h1>
              <p className="text-xl md:text-2xl text-[var(--color-official-text-muted)] font-light">
                {office} &middot; <span className="font-medium text-[var(--color-official-text)]">{party}</span>
              </p>
              <p className="mt-3 text-xs font-mono uppercase tracking-widest text-[var(--color-official-text-muted)]">
                Profile updated {formatDateTime(politician.last_updated)}
              </p>
            </div>

            <OfficialContactCard politicianId={politician.id} initialContact={initialContact} />
          </div>
        </div>

        <div className="border-b border-[var(--color-official-border)] mb-8 overflow-x-auto no-scrollbar">
          <div className="flex space-x-8 min-w-max px-2" role="tablist" aria-label="Profile data sections">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => selectTab(tab.id)}
                className={`py-4 px-2 font-bold text-lg tab-btn cursor-pointer ${
                  activeTab === tab.id
                    ? tab.id === 'media' ? 'active-network text-[var(--color-warning-badge)]' : 'active text-[var(--color-official-link)]'
                    : 'text-[var(--color-official-text-muted)] hover:text-[var(--color-official-text)]'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-[400px]">
          {activeTab === 'financial' && <FinancialDisclosuresTab politicianId={politician.id} />}
          {activeTab === 'donors' && <CampaignDonorsTab politicianId={politician.id} />}
          {activeTab === 'votes' && <VotingRecordTab politicianId={politician.id} />}
          {activeTab === 'connections' && (
            <ConnectionsTab key={politician.id} politicianId={politician.id} politicianName={politician.full_name} />
          )}
          {activeTab === 'media' && <MediaMentionsTab politicianId={politician.id} />}
        </div>
      </main>
    </div>
  );
}
