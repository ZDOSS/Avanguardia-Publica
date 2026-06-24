"use client";

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  fetchConnections,
  type ConnectionsBundle,
  type CoVoteConnection,
} from '@/lib/connections';
import { isUuid } from '@/lib/ids';
import { profilePath } from '@/lib/routes';

// A connection rendered as a node in the hub-and-spoke mini-graph.
interface GraphNode {
  id: string | null;        // politician id for an internal link, else null
  label: string;
  weight: number;           // drives edge thickness
  kind: 'donor' | 'ally' | 'opponent' | 'tie';
}

const KIND_COLOR: Record<GraphNode['kind'], string> = {
  donor: 'var(--color-official-link)',
  ally: 'var(--color-official-link)',
  opponent: 'var(--color-warning-badge)',
  tie: 'var(--color-warning-badge)',
};

function firstName(name: string): string {
  // Compact label for the graph so nodes don't overlap.
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : name;
}

/** Pick the strongest connections across all types for the at-a-glance graph. */
function buildGraphNodes(data: ConnectionsBundle): GraphNode[] {
  const donors: GraphNode[] = data.sharedDonors.slice(0, 3).map((d) => ({
    id: d.politician_id,
    label: firstName(d.full_name),
    weight: d.shared_donor_count,
    kind: 'donor',
  }));
  const allies: GraphNode[] = data.coVotes
    .filter((c) => c.agreement_rate >= 0.5)
    .slice(0, 3)
    .map((c) => ({ id: c.politician_id, label: firstName(c.full_name), weight: c.agree_count, kind: 'ally' }));
  const opponents: GraphNode[] = data.coVotes
    .filter((c) => c.agreement_rate < 0.5)
    .slice(0, 2)
    .map((c) => ({ id: c.politician_id, label: firstName(c.full_name), weight: c.disagree_count, kind: 'opponent' }));
  const ties: GraphNode[] = data.networkTies.slice(0, 2).map((t) => ({
    id: t.related_politician_id,
    label: firstName(t.related_name),
    weight: 1,
    kind: 'tie',
  }));
  // Dedupe across lanes only by politician id: the same tracked person can appear as both
  // a shared donor and a co-voting ally, which would otherwise draw two overlapping nodes.
  // id-less nodes (external network-tie entities) are kept as-is — they're already unique
  // by name within networkTies, and keying them by their shortened label could silently
  // drop a distinct entity whose label collides (e.g. two "John S.").
  const seenIds = new Set<string>();
  const unique: GraphNode[] = [];
  for (const n of [...donors, ...allies, ...opponents, ...ties]) {
    if (n.id) {
      if (seenIds.has(n.id)) continue;
      seenIds.add(n.id);
    }
    unique.push(n);
  }
  return unique.slice(0, 8);
}

function MiniGraph({ center, nodes }: { center: string; nodes: GraphNode[] }) {
  const cx = 200;
  const cy = 150;
  const r = 110;
  const maxW = Math.max(1, ...nodes.map((n) => n.weight));

  return (
    <svg viewBox="0 0 400 300" className="w-full h-auto" role="img" aria-label="Connections graph">
      {nodes.map((n, i) => {
        const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        const stroke = 1.5 + (n.weight / maxW) * 5;
        return (
          <g key={`${n.label}-${i}`}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke={KIND_COLOR[n.kind]} strokeWidth={stroke} strokeOpacity={0.5} />
            <circle cx={x} cy={y} r={6} fill={KIND_COLOR[n.kind]} />
            <text
              x={x}
              y={y + (Math.sin(angle) >= 0 ? 18 : -12)}
              textAnchor="middle"
              fontSize="11"
              fill="var(--color-official-text-muted)"
            >
              {n.label}
            </text>
          </g>
        );
      })}
      {/* Center node = this politician, drawn last so it sits on top. */}
      <circle cx={cx} cy={cy} r={10} fill="var(--color-official-text)" />
      <text x={cx} y={cy - 16} textAnchor="middle" fontSize="12" fontWeight="700" fill="var(--color-official-text)">
        {firstName(center)}
      </text>
    </svg>
  );
}

function PersonCardLink({ id, children }: { id: string | null; children: React.ReactNode }) {
  if (id) {
    return (
      <Link href={profilePath(id)} className="group block premium-card p-4 hover:border-[var(--color-official-link)] transition-colors bg-[var(--color-official-bg)]">
        {children}
      </Link>
    );
  }
  return <div className="premium-card p-4 bg-[var(--color-official-bg)]">{children}</div>;
}

function CoVoteCard({ c }: { c: CoVoteConnection }) {
  const ally = c.agreement_rate >= 0.5;
  return (
    <PersonCardLink id={c.politician_id}>
      <div className="flex justify-between items-start gap-3">
        <div>
          <div className="font-bold group-hover:text-[var(--color-official-link)]">{c.full_name}</div>
          <div className="text-xs text-[var(--color-official-text-muted)]">{c.current_office}</div>
        </div>
        <span
          className={`shrink-0 px-2 py-1 rounded text-xs font-bold uppercase tracking-wider border bg-[var(--color-official-bg-alt)] border-[var(--color-official-border)] ${
            ally ? 'text-[var(--color-official-link)]' : 'text-[var(--color-warning-badge)]'
          }`}
        >
          {Math.round(c.agreement_rate * 100)}% agree
        </span>
      </div>
      <div className="mt-2 text-xs font-mono text-[var(--color-official-text-muted)]">
        {c.agree_count} together · {c.disagree_count} opposed · {c.shared_total} shared roll calls
      </div>
    </PersonCardLink>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-text-muted)] mb-4">{children}</h3>;
}

const EMPTY_BUNDLE: ConnectionsBundle = { sharedDonors: [], coVotes: [], networkTies: [] };

export default function ConnectionsTab({ politicianId, politicianName }: { politicianId: string; politicianName: string }) {
  // Mock/non-UUID profiles have no DB row, so the RPCs would error — start them in a
  // resolved-empty state (initialized from props, so the effect never setStates
  // synchronously, which the react-hooks lint forbids).
  const hasLiveProfileId = isUuid(politicianId);
  const [data, setData] = useState<ConnectionsBundle | null>(hasLiveProfileId ? null : EMPTY_BUNDLE);
  const [loading, setLoading] = useState(hasLiveProfileId);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!hasLiveProfileId) return;
    let cancelled = false;
    fetchConnections(politicianId)
      .then((d) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch((e) => { if (!cancelled) { console.error('Failed to load connections:', e); setError(true); setLoading(false); } });
    return () => { cancelled = true; };
  }, [politicianId, hasLiveProfileId]);

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-48 premium-card" />
        <div className="h-24 premium-card" />
      </div>
    );
  }

  if (error) {
    return <div className="p-8 premium-card text-center text-[var(--color-warning-badge)]">Could not load connections. Please try again later.</div>;
  }

  // After the loading/error guards above, data is set; this explicit check avoids a
  // non-null assertion and is a safe no-op render if it somehow isn't.
  if (!data) return null;
  const bundle = data;
  const allies = bundle.coVotes.filter((c) => c.agreement_rate >= 0.5).sort((a, b) => b.agree_count - a.agree_count);
  const opponents = bundle.coVotes.filter((c) => c.agreement_rate < 0.5).sort((a, b) => b.disagree_count - a.disagree_count);
  const graphNodes = buildGraphNodes(bundle);
  const isEmpty = !bundle.sharedDonors.length && !bundle.coVotes.length && !bundle.networkTies.length;

  if (isEmpty) {
    return (
      <div className="p-8 premium-card text-center text-[var(--color-official-text-muted)]">
        No cross-referenced connections found yet. Co-voting connections appear once roll-call data has been
        re-ingested with stable roll-call ids; shared-donor links require overlapping FEC donors.
      </div>
    );
  }

  return (
    <div className="space-y-10">
      {/* At-a-glance mini-graph */}
      {graphNodes.length > 0 && (
        <div className="premium-card p-4">
          <SectionHeading>Connection Map</SectionHeading>
          <MiniGraph center={politicianName} nodes={graphNodes} />
          <div className="flex flex-wrap gap-4 justify-center mt-2 text-xs text-[var(--color-official-text-muted)]">
            <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-full inline-block" style={{ background: 'var(--color-official-link)' }} /> Shared donors / voting allies</span>
            <span className="inline-flex items-center gap-1"><span className="w-3 h-3 rounded-full inline-block" style={{ background: 'var(--color-warning-badge)' }} /> Opponents / network ties</span>
          </div>
        </div>
      )}

      {/* Shared donors (verified) */}
      {bundle.sharedDonors.length > 0 && (
        <section>
          <SectionHeading>Shared Donors</SectionHeading>
          <div className="grid gap-4 md:grid-cols-2">
            {bundle.sharedDonors.map((d) => (
              <PersonCardLink key={d.politician_id} id={d.politician_id}>
                <div className="font-bold">{d.full_name}</div>
                <div className="text-xs text-[var(--color-official-text-muted)]">{d.current_office}</div>
                <div className="mt-2 text-xs font-mono text-[var(--color-official-text-muted)]">
                  {d.shared_donor_count} shared donor{d.shared_donor_count === 1 ? '' : 's'}
                  {/* Only show a dollar figure when we actually have one — FEC rows can
                      carry NULL/0 amounts, and a bare "$0" reads as a real total. */}
                  {d.shared_total_amount > 0 && <> · ${Math.round(d.shared_total_amount).toLocaleString()}</>}
                </div>
              </PersonCardLink>
            ))}
          </div>
        </section>
      )}

      {/* Co-voting (verified) */}
      {(allies.length > 0 || opponents.length > 0) && (
        <section>
          <SectionHeading>Voting Allies &amp; Opponents</SectionHeading>
          <div className="grid gap-4 md:grid-cols-2">
            {allies.slice(0, 6).map((c) => <CoVoteCard key={c.politician_id} c={c} />)}
            {opponents.slice(0, 6).map((c) => <CoVoteCard key={c.politician_id} c={c} />)}
          </div>
        </section>
      )}

      {/* Network ties (UNVERIFIED — Visual Firewall) */}
      {bundle.networkTies.length > 0 && (
        <section className="visual-firewall">
          <div className="mb-6">
            <span className="warning-badge">Third-Party Data - Unverified</span>
            <p className="text-sm opacity-80 mt-2 max-w-3xl">
              Network ties are ingested from LittleSis by name matching and have not been verified against official records.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {bundle.networkTies.map((t, i) => {
              const inner = (
                <>
                  <div className="flex justify-between items-start gap-3">
                    <div className="font-bold">{t.related_name}</div>
                    {t.relationship_type && (
                      <span className="shrink-0 text-xs font-bold uppercase tracking-wider text-[var(--color-official-text-muted)] bg-[var(--color-official-bg-alt)] px-2 py-1 rounded">{t.relationship_type}</span>
                    )}
                  </div>
                </>
              );
              const cardClass = "block p-4 bg-[var(--color-official-bg)] border border-[var(--color-official-border)] rounded-xl transition-colors";
              if (t.related_politician_id) {
                return <Link key={`${t.related_name}-${i}`} href={profilePath(t.related_politician_id)} className={`${cardClass} hover:border-[var(--color-official-link)]`}>{inner}</Link>;
              }
              if (t.url) {
                return (
                  <a key={`${t.related_name}-${i}`} href={t.url} target="_blank" rel="noreferrer" className={`${cardClass} hover:border-[var(--color-official-link)]`}>
                    {inner}
                    <div className="mt-2 text-xs text-[var(--color-official-link)] font-bold uppercase tracking-wider">LittleSis &rarr;</div>
                  </a>
                );
              }
              // No internal profile and no source URL — render a non-interactive card
              // rather than a dead href="#" anchor.
              return <div key={`${t.related_name}-${i}`} className={cardClass}>{inner}</div>;
            })}
          </div>
        </section>
      )}
    </div>
  );
}
