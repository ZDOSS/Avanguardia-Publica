"use client";

import { useState } from 'react';
import Link from 'next/link';
import ConnectionsTab from './ConnectionsTab';

export interface FinancialDisclosure {
  id: string;
  filing_date: string;
  transaction_type: string;
  asset_name: string;
  asset_value_range: string;
}

export interface CampaignDonor {
  id: string;
  donation_date: string;
  donor_name: string;
  pac_status: boolean;
  amount: number;
}

export interface VotingRecord {
  id: string;
  bill_name: string;
  bill_summary: string;
  vote_date: string;
  vote_cast: string;
}

export interface ContactInfo {
  office_address: string;
  phone_number: string;
  official_website: string;
}

export interface UnconfirmedMention {
  id: string;
  source_api: string;
  sentiment_score: number | null;
  content_summary: string;
  url: string | null;
}

export interface PoliticianData {
  id: string;
  full_name: string;
  current_office: string;
  party: string;
  contact_info?: ContactInfo[];
  financial_disclosures?: FinancialDisclosure[];
  campaign_donors?: CampaignDonor[];
  voting_records?: VotingRecord[];
}

interface Props {
  politician: PoliticianData;
  unconfirmed: UnconfirmedMention[];
}

export default function PoliticianClient({ politician, unconfirmed }: Props) {
  const [activeTab, setActiveTab] = useState<'financial' | 'donors' | 'voting' | 'connections' | 'media'>('financial');

  const contact = politician?.contact_info?.[0] || {} as Partial<ContactInfo>;

  return (
    <div className="min-h-screen bg-[var(--color-official-bg)] text-[var(--color-official-text)] transition-colors">
      {/* Navigation */}
      <nav className="glass-header sticky top-0 z-50 p-4">
        <div className="max-w-6xl mx-auto flex justify-between items-center">
          <Link href="/" className="text-[var(--color-official-link)] hover:underline font-bold transition-all hover:tracking-wide">
            &larr; Back to Search
          </Link>
          <span className="text-[var(--color-official-text-muted)] font-mono text-sm uppercase tracking-widest">Avanguardia Publica</span>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto p-4 py-8 md:py-12">
        {/* The Hub (Profile Header) */}
        <div className="flex flex-col md:flex-row gap-8 mb-12">
          {/* Portrait Placeholder */}
          <div className="w-48 h-64 bg-[var(--color-official-bg-alt)] border border-[var(--color-official-border)] flex items-center justify-center rounded-2xl shadow-sm shrink-0">
            <span className="text-[var(--color-official-text-muted)] text-sm uppercase tracking-widest">Portrait</span>
          </div>
          
          <div className="flex flex-col justify-between w-full">
            <div>
              <h1 className="text-4xl md:text-5xl font-extrabold mb-2 text-[var(--color-official-text)]">
                {politician.full_name}
              </h1>
              <p className="text-xl md:text-2xl text-[var(--color-official-text-muted)] font-light">
                {politician.current_office} &middot; <span className="font-medium text-[var(--color-official-text)]">{politician.party}</span>
              </p>
            </div>
            
            <div className="mt-8 p-6 premium-card max-w-2xl">
              <h2 className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-text-muted)] mb-4">Official Contact</h2>
              <div className="space-y-3 text-sm md:text-base">
                <p><strong className="font-semibold text-[var(--color-official-text-muted)] mr-2">Address:</strong> {contact.office_address || 'N/A'}</p>
                <p><strong className="font-semibold text-[var(--color-official-text-muted)] mr-2">Phone:</strong> {contact.phone_number || 'N/A'}</p>
                <p><strong className="font-semibold text-[var(--color-official-text-muted)] mr-2">Website:</strong> 
                  {contact.official_website ? (
                    <a href={contact.official_website} className="text-[var(--color-official-link)] hover:underline ml-1" target="_blank" rel="noreferrer">{contact.official_website}</a>
                  ) : 'N/A'}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Tabbed Navigation */}
        <div className="border-b border-[var(--color-official-border)] mb-8 overflow-x-auto no-scrollbar">
          <div className="flex space-x-8 min-w-max px-2">
            {[
              { id: 'financial', label: 'Financial Disclosures' },
              { id: 'donors', label: 'Campaign Donors' },
              { id: 'voting', label: 'Voting Record' },
              { id: 'connections', label: 'Connections' },
              { id: 'media', label: 'Media' }
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as 'financial' | 'donors' | 'voting' | 'connections' | 'media')}
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

        {/* The Spokes (Data Views) */}
        <div className="min-h-[400px]">
          {/* Financial Disclosures */}
          {activeTab === 'financial' && (
            <div className="overflow-x-auto premium-card">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[var(--color-official-bg-alt)] border-b border-[var(--color-official-border)]">
                    <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Date</th>
                    <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Transaction</th>
                    <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Asset Name</th>
                    <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Value Range</th>
                  </tr>
                </thead>
                <tbody>
                  {politician.financial_disclosures?.length ? politician.financial_disclosures.map((item: FinancialDisclosure) => (
                    <tr key={item.id} className="border-b border-[var(--color-official-border)] hover:bg-[var(--color-official-bg-alt)]/50 transition-colors">
                      <td className="p-4 whitespace-nowrap text-sm">{item.filing_date}</td>
                      <td className="p-4"><span className="px-2 py-1 bg-[var(--color-official-bg-alt)] text-[var(--color-official-text)] border border-[var(--color-official-border)] rounded text-xs font-bold uppercase tracking-wider">{item.transaction_type}</span></td>
                      <td className="p-4 font-medium">{item.asset_name}</td>
                      <td className="p-4 text-[var(--color-official-text-muted)]">{item.asset_value_range}</td>
                    </tr>
                  )) : (
                    <tr><td colSpan={4} className="p-8 text-center text-[var(--color-official-text-muted)]">No financial disclosures on record.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* Campaign Donors */}
          {activeTab === 'donors' && (
             <div className="overflow-x-auto premium-card">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[var(--color-official-bg-alt)] border-b border-[var(--color-official-border)]">
                    <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Date</th>
                    <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Donor Name</th>
                    <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Type</th>
                    <th className="p-4 font-semibold text-sm tracking-wide text-[var(--color-official-text-muted)] uppercase">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {politician.campaign_donors?.length ? politician.campaign_donors.map((item: CampaignDonor) => (
                    <tr key={item.id} className="border-b border-[var(--color-official-border)] hover:bg-[var(--color-official-bg-alt)]/50 transition-colors">
                      <td className="p-4 whitespace-nowrap text-sm">{item.donation_date}</td>
                      <td className="p-4 font-medium">{item.donor_name}</td>
                      <td className="p-4">
                        {item.pac_status ? (
                          <span className="px-2 py-1 bg-[var(--color-official-bg-alt)] text-[var(--color-official-text-muted)] border border-[var(--color-official-border)] rounded text-xs font-bold uppercase tracking-wider">PAC</span>
                        ) : (
                          <span className="px-2 py-1 bg-[var(--color-official-bg-alt)] text-[var(--color-official-link)] border border-[var(--color-official-border)] rounded text-xs font-bold uppercase tracking-wider">Individual</span>
                        )}
                      </td>
                      <td className="p-4 font-mono font-bold">${item.amount}</td>
                    </tr>
                  )) : (
                    <tr><td colSpan={4} className="p-8 text-center text-[var(--color-official-text-muted)]">No campaign donors on record.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* Voting Record */}
          {activeTab === 'voting' && (
            <div className="space-y-4">
              {politician.voting_records?.length ? politician.voting_records.map((item: VotingRecord) => (
                <div key={item.id} className="p-6 premium-card flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                  <div>
                    <h3 className="font-bold text-xl mb-2 leading-tight">{item.bill_name}</h3>
                    <p className="text-[var(--color-official-text-muted)] mb-3 text-sm md:text-base">{item.bill_summary}</p>
                    <span className="text-xs font-mono uppercase text-[var(--color-official-text-muted)] tracking-widest">{item.vote_date}</span>
                  </div>
                  <div className="shrink-0">
                    <span className={`px-4 py-2 rounded-full font-bold text-sm tracking-widest uppercase border bg-[var(--color-official-bg-alt)] border-[var(--color-official-border)] ${
                      item.vote_cast === 'Yea' ? 'text-[var(--color-official-link)]' : 'text-[var(--color-warning-badge)]'
                    }`}>
                      {item.vote_cast}
                    </span>
                  </div>
                </div>
              )) : (
                <div className="p-8 premium-card text-center text-[var(--color-official-text-muted)]">No voting records available.</div>
              )}
            </div>
          )}

          {/* Connections (cross-referenced individuals — live from the DB).
              key={politician.id} remounts the tab on a soft navigation to another profile,
              re-initialising its loading/error/data state instead of leaking a stale error
              banner over the next profile's data. */}
          {activeTab === 'connections' && (
            <ConnectionsTab key={politician.id} politicianId={politician.id} politicianName={politician.full_name} />
          )}

          {/* Media (VISUAL FIREWALL) — third-party news & mentions */}
          {activeTab === 'media' && (
            <div className="visual-firewall">
              <div className="mb-8">
                <span className="warning-badge animate-pulse">Third-Party Data - Unverified</span>
                <p className="text-sm opacity-80 mt-2 max-w-3xl">The following information is ingested automatically from third-party APIs based on name matching. It has not been verified against official government records.</p>
              </div>
              
              <div className="grid gap-4 md:grid-cols-2">
                {unconfirmed?.length ? unconfirmed.map((item: UnconfirmedMention) => (
                  <div key={item.id} className="p-5 bg-[var(--color-official-bg)] border border-[var(--color-official-border)] rounded-xl shadow-sm hover:shadow-md transition-shadow">
                    <div className="flex justify-between items-start mb-3">
                      <span className="text-xs font-bold text-[var(--color-official-text-muted)] uppercase tracking-widest bg-[var(--color-official-bg-alt)] px-2 py-1 rounded">
                        {item.source_api}
                      </span>
                      {item.sentiment_score !== null && (
                        <span className="text-xs font-mono text-[var(--color-official-text-muted)]">Sentiment: {item.sentiment_score}</span>
                      )}
                    </div>
                    <p className="mb-4 text-sm leading-relaxed">{item.content_summary}</p>
                    {item.url && (
                      <a href={item.url} target="_blank" rel="noreferrer" className="text-[var(--color-official-link)] hover:underline text-xs font-bold uppercase tracking-wider inline-flex items-center">
                        Source Link <span className="ml-1">&rarr;</span>
                      </a>
                    )}
                  </div>
                )) : (
                  <div className="col-span-2 p-8 text-center opacity-70">No unconfirmed mentions found.</div>
                )}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
