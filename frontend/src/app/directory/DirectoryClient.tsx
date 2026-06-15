"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";

// ─── Types ────────────────────────────────────────────────────────────────────
interface Politician {
  id: string;
  full_name: string;
  current_office: string;
  party: string;
}

interface CategoryNode {
  label: string;
  icon: string;
  children?: CategoryNode[];
  politicians: Politician[];
}

// ─── Office → Category Mapping ────────────────────────────────────────────────
// Rules are checked in order; first match wins.
type Rule = { keywords: string[]; path: string[] };

const RULES: Rule[] = [
  // Federal – Executive
  { keywords: ["president of the united states"], path: ["Federal Government", "Executive Branch", "Office of the President"] },
  { keywords: ["vice president"], path: ["Federal Government", "Executive Branch", "Office of the President"] },
  { keywords: ["secretary of state", "secretary of the treasury", "secretary of defense",
      "attorney general", "secretary of", "administrator of", "director of national"],
    path: ["Federal Government", "Executive Branch", "Cabinet & Agencies"] },

  // Federal – Legislative
  { keywords: ["u.s. senator", "united states senator", "senator from"],
    path: ["Federal Government", "Legislative Branch", "Senate"] },
  { keywords: ["u.s. representative", "representative from", "member of the u.s. house",
      "member of congress", "house of representatives"],
    path: ["Federal Government", "Legislative Branch", "House of Representatives"] },

  // Federal – Judicial
  { keywords: ["supreme court", "chief justice", "associate justice"],
    path: ["Federal Government", "Judicial Branch", "Supreme Court"] },
  { keywords: ["circuit court", "district court", "federal judge", "u.s. judge"],
    path: ["Federal Government", "Judicial Branch", "Federal Courts"] },

  // State – Executive
  { keywords: ["governor of", "governor,"],
    path: ["State & Territorial Governments", "State Executive", "Governor"] },
  { keywords: ["lieutenant governor"],
    path: ["State & Territorial Governments", "State Executive", "Lieutenant Governor"] },
  { keywords: ["state attorney general"],
    path: ["State & Territorial Governments", "State Executive", "State AG & Cabinet"] },
  { keywords: ["secretary of state of", "state treasurer", "state comptroller", "state auditor"],
    path: ["State & Territorial Governments", "State Executive", "State AG & Cabinet"] },

  // State – Legislative
  { keywords: ["state senator", "state senate"],
    path: ["State & Territorial Governments", "State Legislature", "State Senate"] },
  { keywords: ["state representative", "state assembly", "state house"],
    path: ["State & Territorial Governments", "State Legislature", "State House / Assembly"] },

  // Local
  { keywords: ["mayor of", "mayor,"],
    path: ["Local Government", "Municipal", "Mayor"] },
  { keywords: ["city council", "alderman", "alderperson"],
    path: ["Local Government", "Municipal", "City Council"] },
  { keywords: ["county", "county commissioner", "county executive", "county supervisor"],
    path: ["Local Government", "County", "County Officials"] },
  { keywords: ["school board", "school district"],
    path: ["Local Government", "Special Districts", "School Board"] },
];

function classifyPolitician(office: string): string[] {
  const lower = office.toLowerCase();
  for (const rule of RULES) {
    if (rule.keywords.some((kw) => lower.includes(kw))) {
      return rule.path;
    }
  }
  return ["Uncategorized"];
}

// ─── Build nested tree ────────────────────────────────────────────────────────
function buildTree(politicians: Politician[]): CategoryNode[] {
  // We use a Map keyed by full path segments as a nested record
  const tree: Map<string, CategoryNode> = new Map();

  const getOrCreate = (map: Map<string, CategoryNode>, key: string, icon: string): CategoryNode => {
    if (!map.has(key)) map.set(key, { label: key, icon, politicians: [] });
    return map.get(key)!;
  };

  // We'll build a three-level nested structure: branch → section → sub
  const branchMap = new Map<string, { node: CategoryNode; sections: Map<string, { node: CategoryNode; subs: Map<string, CategoryNode> }> }>();

  const ICONS: Record<string, string> = {
    "Federal Government": "🏛️",
    "State & Territorial Governments": "🗺️",
    "Local Government": "🏙️",
    "Uncategorized": "📋",
    "Executive Branch": "🤝",
    "Legislative Branch": "⚖️",
    "Judicial Branch": "🔨",
    "State Executive": "🏷️",
    "State Legislature": "📜",
    "Municipal": "🏠",
    "County": "🌾",
    "Special Districts": "🏫",
  };

  for (const pol of politicians) {
    const path = classifyPolitician(pol.current_office || "");
    const [branch, section, sub] = path;

    if (!branchMap.has(branch)) {
      branchMap.set(branch, {
        node: { label: branch, icon: ICONS[branch] || "📁", politicians: [] },
        sections: new Map(),
      });
    }
    const branchEntry = branchMap.get(branch)!;

    if (!section) {
      branchEntry.node.politicians.push(pol);
      continue;
    }

    if (!branchEntry.sections.has(section)) {
      branchEntry.sections.set(section, {
        node: { label: section, icon: ICONS[section] || "📂", politicians: [] },
        subs: new Map(),
      });
    }
    const sectionEntry = branchEntry.sections.get(section)!;

    if (!sub) {
      sectionEntry.node.politicians.push(pol);
      continue;
    }

    if (!sectionEntry.subs.has(sub)) {
      sectionEntry.subs.set(sub, { label: sub, icon: "👤", politicians: [] });
    }
    sectionEntry.subs.get(sub)!.politicians.push(pol);
  }

  // Convert to array structure
  const result: CategoryNode[] = [];
  for (const [, bEntry] of branchMap) {
    const sectionNodes: CategoryNode[] = [];
    for (const [, sEntry] of bEntry.sections) {
      const subNodes: CategoryNode[] = [];
      for (const [, sub] of sEntry.subs) {
        if (sub.politicians.length > 0) subNodes.push(sub);
      }
      const sNode: CategoryNode = { ...sEntry.node, children: subNodes };
      sectionNodes.push(sNode);
    }
    const bNode: CategoryNode = { ...bEntry.node, children: sectionNodes };
    result.push(bNode);
  }

  return result;
}

// ─── Sub-category accordion ───────────────────────────────────────────────────
function SubCategoryAccordion({ node, depth = 0 }: { node: CategoryNode; depth?: number }) {
  const [open, setOpen] = useState(depth === 0);
  const totalPols = countPoliticians(node);

  return (
    <div className={`${depth === 0 ? "mb-4" : "mt-2"}`}>
      <button
        onClick={() => setOpen((p) => !p)}
        className={`w-full flex items-center gap-3 text-left transition-all group cursor-pointer
          ${depth === 0
            ? "p-5 premium-card bg-[var(--color-official-bg)] hover:bg-[var(--color-official-bg-alt)]"
            : depth === 1
            ? "px-4 py-3 rounded-lg bg-[var(--color-official-bg-alt)]/60 hover:bg-[var(--color-official-bg-alt)] border border-[var(--color-official-border)]"
            : "px-3 py-2 rounded bg-[var(--color-official-bg)]/50 hover:bg-[var(--color-official-bg-alt)]/50"
          }`}
      >
        <span className="text-2xl shrink-0">{node.icon}</span>
        <div className="flex-1 min-w-0">
          <span className={`font-bold ${depth === 0 ? "text-xl" : depth === 1 ? "text-base" : "text-sm"} text-[var(--color-official-text)] group-hover:text-[var(--color-official-link)] transition-colors`}>
            {node.label}
          </span>
          <span className="ml-2 text-xs font-mono text-[var(--color-official-text-muted)] bg-[var(--color-official-bg)] border border-[var(--color-official-border)] px-2 py-0.5 rounded-full">
            {totalPols}
          </span>
        </div>
        <span className={`text-[var(--color-official-text-muted)] transition-transform duration-200 shrink-0 ${open ? "rotate-90" : ""}`}>
          ▶
        </span>
      </button>

      {open && (
        <div className={`${depth === 0 ? "mt-3 ml-4 space-y-2" : "mt-2 ml-4 space-y-1"}`}>
          {/* Nested children */}
          {node.children?.map((child) => (
            <SubCategoryAccordion key={child.label} node={child} depth={depth + 1} />
          ))}

          {/* Direct politician cards */}
          {node.politicians.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-2">
              {node.politicians.map((p) => (
                <PoliticianCard key={p.id} politician={p} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function countPoliticians(node: CategoryNode): number {
  let count = node.politicians.length;
  for (const child of node.children || []) count += countPoliticians(child);
  return count;
}

// ─── Politician card ──────────────────────────────────────────────────────────
const PARTY_COLORS: Record<string, string> = {
  republican: "text-red-400",
  democrat: "text-blue-400",
  democratic: "text-blue-400",
  independent: "text-purple-400",
  libertarian: "text-yellow-400",
  green: "text-green-400",
};

function PoliticianCard({ politician }: { politician: Politician }) {
  const partyKey = (politician.party || "").toLowerCase();
  const partyColor = PARTY_COLORS[partyKey] || "text-[var(--color-official-text-muted)]";

  return (
    <Link
      href={`/${politician.id}`}
      className="group block p-4 rounded-xl bg-[var(--color-official-bg)] border border-[var(--color-official-border)] hover:border-[var(--color-official-link)] hover:shadow-lg transition-all duration-200 hover:-translate-y-0.5"
    >
      <div className="font-semibold text-sm group-hover:text-[var(--color-official-link)] transition-colors leading-tight mb-1">
        {politician.full_name}
      </div>
      <div className="text-xs text-[var(--color-official-text-muted)] leading-snug mb-2 line-clamp-2">
        {politician.current_office}
      </div>
      <div className={`text-xs font-mono font-bold uppercase tracking-wider ${partyColor}`}>
        {politician.party || "Unknown"}
      </div>
    </Link>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function DirectoryClient() {
  const [politicians, setPoliticians] = useState<Politician[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<string>("All");

  useEffect(() => {
    async function load() {
      try {
        const { data, error } = await supabase
          .from("politicians")
          .select("id, full_name, current_office, party")
          .order("full_name");
        if (error) throw error;
        setPoliticians(data || []);
      } catch (e) {
        console.error("Failed to load politicians:", e);
        setError("Could not connect to the database. Please try again later.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const parties = ["All", ...Array.from(new Set(politicians.map((p) => p.party || "Unknown").filter(Boolean))).sort()];

  const filtered = politicians.filter((p) => {
    const matchSearch =
      !search ||
      p.full_name.toLowerCase().includes(search.toLowerCase()) ||
      (p.current_office || "").toLowerCase().includes(search.toLowerCase());
    const matchParty = activeFilter === "All" || p.party === activeFilter;
    return matchSearch && matchParty;
  });

  const tree = buildTree(filtered);
  const total = filtered.length;

  return (
    <div className="min-h-screen bg-[var(--color-official-bg)] text-[var(--color-official-text)]">
      {/* Navigation */}
      <nav className="glass-header sticky top-0 z-50 p-4">
        <div className="max-w-6xl mx-auto flex justify-between items-center">
          <Link href="/" className="text-[var(--color-official-link)] hover:underline font-bold transition-all hover:tracking-wide">
            ← Back to Search
          </Link>
          <span className="text-[var(--color-official-text-muted)] font-mono text-sm uppercase tracking-widest">
            Avanguardia Publica
          </span>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto p-4 py-8 md:py-12">
        {/* Header */}
        <div className="mb-10">
          <h1 className="text-4xl md:text-5xl font-extrabold mb-3 bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-500 dark:from-blue-400 dark:to-indigo-300">
            Government Directory
          </h1>
          <p className="text-[var(--color-official-text-muted)] text-lg">
            U.S. politicians organized by branch, chamber, and office.
          </p>
        </div>

        {/* Filter + Search bar */}
        <div className="mb-8 premium-card p-4 flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            placeholder="Filter by name or office…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent border-b border-[var(--color-official-border)] focus:border-[var(--color-official-link)] px-2 py-2 text-base focus:outline-none transition-colors"
          />
          <div className="flex flex-wrap gap-2 items-center">
            {parties.slice(0, 6).map((party) => (
              <button
                key={party}
                onClick={() => setActiveFilter(party)}
                className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border transition-all cursor-pointer
                  ${activeFilter === party
                    ? "bg-[var(--color-official-link)] text-white border-[var(--color-official-link)]"
                    : "border-[var(--color-official-border)] text-[var(--color-official-text-muted)] hover:border-[var(--color-official-link)]"
                  }`}
              >
                {party}
              </button>
            ))}
          </div>
        </div>

        {/* State */}
        {loading && (
          <div className="space-y-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="animate-pulse premium-card p-5 h-20 bg-[var(--color-official-bg-alt)]" />
            ))}
          </div>
        )}

        {error && (
          <div className="p-8 text-center premium-card border-red-500/30">
            <p className="text-red-400 font-semibold">{error}</p>
          </div>
        )}

        {!loading && !error && (
          <>
            <p className="text-sm text-[var(--color-official-text-muted)] mb-6">
              Showing <strong className="text-[var(--color-official-text)]">{total.toLocaleString()}</strong> politicians
              {search && <> matching <em>&quot;{search}&quot;</em></>}
            </p>

            {tree.length === 0 ? (
              <div className="p-12 text-center text-[var(--color-official-text-muted)] premium-card">
                No politicians match your current filters.
              </div>
            ) : (
              <div className="space-y-3">
                {tree.map((branch) => (
                  <SubCategoryAccordion key={branch.label} node={branch} depth={0} />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
