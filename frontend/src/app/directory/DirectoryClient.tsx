"use client";

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { fetchAllPoliticians, type PoliticianSummary } from "@/lib/politicians";
import { GOV_STRUCTURE, type GovNode, type GovPath } from "@/lib/governmentStructure";
import { US_STATES, resolveStateToken, zipToState, officeMatchesState } from "@/lib/location";
import { profilePath } from "@/lib/routes";

type Politician = PoliticianSummary;

// ─── Office → taxonomy path ─────────────────────────────────────────────────
// Rules are checked in order; first match wins. Each `path` is a list of node
// labels into GOV_STRUCTURE (root → leaf) that the politician attaches to. State
// & Federal rules MUST sit above generic Local rules to avoid substring capture.
const FED = "Federal Government";
const STATE = "State Government (General Model for 50 States)";
const LOCAL = "Local Government";

type Rule = { keywords: string[]; path: GovPath };

const RULES: Rule[] = [
  // State – Executive
  { keywords: ["lieutenant governor"], path: [STATE, "State Executive Branch", "Lieutenant Governor"] },
  { keywords: ["governor of", "governor,", "governor"], path: [STATE, "State Executive Branch", "The Governor (Chief Executive)"] },
  { keywords: ["state attorney general"], path: [STATE, "State Executive Branch", "Elected Executive Officers (Varies by State)", "Attorney General (Chief Legal Officer)"] },
  { keywords: ["secretary of state of"], path: [STATE, "State Executive Branch", "Elected Executive Officers (Varies by State)", "Secretary of State (Elections, Business Registry)"] },
  { keywords: ["state treasurer", "state comptroller"], path: [STATE, "State Executive Branch", "Elected Executive Officers (Varies by State)", "State Treasurer / Comptroller"] },
  { keywords: ["superintendent of public instruction"], path: [STATE, "State Executive Branch", "Elected Executive Officers (Varies by State)", "Superintendent of Public Instruction / Education"] },

  // State – Legislative
  { keywords: ["state senator", "state senate"], path: [STATE, "State Legislative Branch", "State Senate (Upper Chamber)"] },
  { keywords: ["state representative", "state assembly", "state house", "house of delegates", "assembly member"], path: [STATE, "State Legislative Branch", "State House of Representatives / Assembly / House of Delegates (Lower Chamber)"] },

  // Federal – Executive
  { keywords: ["president of the united states"], path: [FED, "Executive Branch", "The President"] },
  { keywords: ["vice president"], path: [FED, "Executive Branch", "The Vice President"] },
  { keywords: ["secretary of", "attorney general", "administrator of", "director of national"], path: [FED, "Executive Branch", "The Cabinet (15 Executive Departments)"] },

  // Federal – Legislative
  { keywords: ["u.s. senator", "us senator", "united states senator", "senator from"], path: [FED, "Legislative Branch (Congress)", "Senate (100 Members)"] },
  { keywords: ["u.s. representative", "us representative", "representative from", "member of the u.s. house", "member of congress", "house of representatives"], path: [FED, "Legislative Branch (Congress)", "House of Representatives (435 Members)"] },

  // Federal – Judicial
  { keywords: ["chief justice"], path: [FED, "Judicial Branch", "Supreme Court of the United States", "Chief Justice"] },
  { keywords: ["associate justice", "supreme court"], path: [FED, "Judicial Branch", "Supreme Court of the United States", "8 Associate Justices"] },

  // Local
  { keywords: ["mayor of", "mayor,", "mayor"], path: [LOCAL, "Municipal Government (Cities, Towns, Villages)", "Executive Branch", "Mayor (Chief Executive)"] },
  { keywords: ["city manager", "town administrator"], path: [LOCAL, "Municipal Government (Cities, Towns, Villages)", "Executive Branch", "City Manager / Town Administrator (Appointed Professional)"] },
  { keywords: ["city council", "alderman", "alderperson", "town board"], path: [LOCAL, "Municipal Government (Cities, Towns, Villages)", "Legislative Branch", "City Council / Board of Aldermen / Town Board"] },
  { keywords: ["sheriff"], path: [LOCAL, "County Government", "Elected County Officials", "County Sheriff (Law Enforcement & Jails)"] },
  { keywords: ["district attorney", "county prosecutor"], path: [LOCAL, "County Government", "Elected County Officials", "District Attorney / County Prosecutor"] },
  { keywords: ["county commissioner", "county executive", "county supervisor", "board of supervisors"], path: [LOCAL, "County Government", "Legislative / Executive Authority", "Board of County Commissioners / Supervisors"] },
  { keywords: ["county"], path: [LOCAL, "County Government"] },
  { keywords: ["school board", "board of education", "school district"], path: [LOCAL, "Special Districts (Independent Entities)", "School Districts (Over 13,000 nationwide)", "Board of Education / School Board (Elected Legislative Body)"] },
];

const UNCATEGORIZED = "Uncategorized";

function classifyToPath(office: string): GovPath {
  const lower = (office || "").toLowerCase();
  for (const rule of RULES) {
    if (rule.keywords.some((kw) => lower.includes(kw))) return rule.path;
  }
  return [UNCATEGORIZED];
}

const LEVEL_ROOT: Record<string, string> = {
  Federal: FED,
  State: STATE,
  Local: LOCAL,
};

const NORMALIZED_LEVEL_ROOT: Record<string, string> = {
  federal: FED,
  state: STATE,
  local: LOCAL,
};

function normalizedClassificationPath(pol: Politician): GovPath | null {
  const level = pol.government_level?.toLowerCase();
  const branch = pol.government_branch?.toLowerCase();
  const officeType = pol.office_type?.toLowerCase();

  if (!level) return null;

  if (level === "federal") {
    if (branch === "executive") {
      if (officeType === "president") return [FED, "Executive Branch", "The President"];
      if (officeType === "vice_president") return [FED, "Executive Branch", "The Vice President"];
      return [FED, "Executive Branch"];
    }

    if (branch === "legislative") {
      if (officeType === "senator") return [FED, "Legislative Branch (Congress)", "Senate (100 Members)"];
      if (officeType === "representative") {
        return [FED, "Legislative Branch (Congress)", "House of Representatives (435 Members)"];
      }
      return [FED, "Legislative Branch (Congress)"];
    }

    if (branch === "judicial") {
      if (officeType === "chief_justice") {
        return [FED, "Judicial Branch", "Supreme Court of the United States", "Chief Justice"];
      }
      if (officeType === "associate_justice") {
        return [FED, "Judicial Branch", "Supreme Court of the United States", "8 Associate Justices"];
      }
      return [FED, "Judicial Branch"];
    }

    return [FED];
  }

  if (level === "state") {
    if (branch === "executive") {
      if (officeType === "governor") return [STATE, "State Executive Branch", "The Governor (Chief Executive)"];
      if (officeType === "lieutenant_governor") return [STATE, "State Executive Branch", "Lieutenant Governor"];
      if (officeType === "attorney_general") {
        return [STATE, "State Executive Branch", "Elected Executive Officers (Varies by State)", "Attorney General (Chief Legal Officer)"];
      }
      if (officeType === "secretary_of_state") {
        return [STATE, "State Executive Branch", "Elected Executive Officers (Varies by State)", "Secretary of State (Elections, Business Registry)"];
      }
      if (officeType === "treasurer" || officeType === "comptroller") {
        return [STATE, "State Executive Branch", "Elected Executive Officers (Varies by State)", "State Treasurer / Comptroller"];
      }
      return [STATE, "State Executive Branch"];
    }

    if (branch === "legislative") {
      if (officeType === "senator") return [STATE, "State Legislative Branch", "State Senate (Upper Chamber)"];
      if (officeType === "representative") {
        return [STATE, "State Legislative Branch", "State House of Representatives / Assembly / House of Delegates (Lower Chamber)"];
      }
      return [STATE, "State Legislative Branch"];
    }

    if (branch === "judicial") return [STATE, "State Judicial Branch"];

    return [STATE];
  }

  if (level === "local") {
    if (officeType === "mayor") {
      return [LOCAL, "Municipal Government (Cities, Towns, Villages)", "Executive Branch", "Mayor (Chief Executive)"];
    }
    if (officeType === "city_manager" || officeType === "town_administrator") {
      return [LOCAL, "Municipal Government (Cities, Towns, Villages)", "Executive Branch", "City Manager / Town Administrator (Appointed Professional)"];
    }
    if (officeType === "council_member") {
      return [LOCAL, "Municipal Government (Cities, Towns, Villages)", "Legislative Branch", "City Council / Board of Aldermen / Town Board"];
    }
    if (officeType === "sheriff") {
      return [LOCAL, "County Government", "Elected County Officials", "County Sheriff (Law Enforcement & Jails)"];
    }
    if (officeType === "district_attorney") {
      return [LOCAL, "County Government", "Elected County Officials", "District Attorney / County Prosecutor"];
    }
    if (officeType === "county_commissioner") {
      return [LOCAL, "County Government", "Legislative / Executive Authority", "Board of County Commissioners / Supervisors"];
    }
    if (officeType === "school_board_member") {
      return [LOCAL, "Special Districts (Independent Entities)", "School Districts (Over 13,000 nationwide)", "Board of Education / School Board (Elected Legislative Body)"];
    }
    return [LOCAL];
  }

  return null;
}

function classifyPoliticianToPath(pol: Politician): GovPath {
  return normalizedClassificationPath(pol) ?? classifyToPath(pol.current_office || "");
}

function politicianLevelRoot(pol: Politician): string {
  const normalizedRoot = pol.government_level
    ? NORMALIZED_LEVEL_ROOT[pol.government_level.toLowerCase()]
    : null;
  return normalizedRoot ?? classifyToPath(pol.current_office || "")[0];
}

// ─── Runtime tree (taxonomy skeleton + attached politicians) ────────────────
interface RuntimeNode {
  label: string;
  icon?: string;
  children: RuntimeNode[];
  politicians: Politician[];
}

function cloneStructure(nodes: GovNode[]): RuntimeNode[] {
  return nodes.map((n) => ({
    label: n.label,
    icon: n.icon,
    children: n.children ? cloneStructure(n.children) : [],
    politicians: [],
  }));
}

function findOrCreate(children: RuntimeNode[], label: string): RuntimeNode {
  let node = children.find((c) => c.label === label);
  if (!node) {
    node = { label, children: [], politicians: [] };
    children.push(node);
  }
  return node;
}

function buildTree(politicians: Politician[]): RuntimeNode[] {
  const roots = cloneStructure(GOV_STRUCTURE);

  for (const pol of politicians) {
    const path = classifyPoliticianToPath(pol);
    let node = findOrCreate(roots, path[0]);
    for (let i = 1; i < path.length; i++) node = findOrCreate(node.children, path[i]);
    node.politicians.push(pol);
  }
  return roots;
}

function countPoliticians(node: RuntimeNode): number {
  let count = node.politicians.length;
  for (const child of node.children) count += countPoliticians(child);
  return count;
}

// ─── Accordion node (renders the nested links) ──────────────────────────────
function TreeNode({
  node,
  depth,
  searching,
}: {
  node: RuntimeNode;
  depth: number;
  searching: boolean;
}) {
  const total = useMemo(() => countPoliticians(node), [node]);

  // Default open state: top level when browsing, or any node with matches while
  // searching. `manual` lets the user override. The whole tree is remounted (via a
  // key on the search/browse context) when that context flips, so this override
  // resets there and auto-expansion tracks the latest results.
  const [manual, setManual] = useState<boolean | null>(null);

  const defaultOpen = searching ? total > 0 : depth === 0;
  const open = manual ?? defaultOpen;

  const hasChildrenWithContent = node.children.length > 0;

  return (
    <div className={depth === 0 ? "mb-4" : "mt-2"}>
      <button
        onClick={() => setManual(!open)}
        className={`w-full flex items-center gap-3 text-left transition-all group cursor-pointer
          ${
            depth === 0
              ? "p-5 premium-card bg-[var(--color-official-bg)] hover:bg-[var(--color-official-bg-alt)]"
              : depth === 1
              ? "px-4 py-3 rounded-lg bg-[var(--color-official-bg-alt)]/60 hover:bg-[var(--color-official-bg-alt)] border border-[var(--color-official-border)]"
              : "px-3 py-2 rounded bg-[var(--color-official-bg)]/50 hover:bg-[var(--color-official-bg-alt)]/50"
          }`}
      >
        {node.icon && <span className="text-2xl shrink-0">{node.icon}</span>}
        <div className="flex-1 min-w-0">
          <span
            className={`font-bold ${
              depth === 0 ? "text-xl" : depth === 1 ? "text-base" : "text-sm"
            } text-[var(--color-official-text)] group-hover:text-[var(--color-official-link)] transition-colors`}
          >
            {node.label}
          </span>
          <span
            className={`ml-2 text-xs font-mono px-2 py-0.5 rounded-full border
              ${
                total > 0
                  ? "text-[var(--color-official-text-muted)] bg-[var(--color-official-bg)] border-[var(--color-official-border)]"
                  : "text-[var(--color-official-text-muted)]/50 border-[var(--color-official-border)]/40"
              }`}
          >
            {total}
          </span>
        </div>
        {(hasChildrenWithContent || node.politicians.length > 0) && (
          <span
            className={`text-[var(--color-official-text-muted)] transition-transform duration-200 shrink-0 ${
              open ? "rotate-90" : ""
            }`}
          >
            ▶
          </span>
        )}
      </button>

      {open && (
        <div className={depth === 0 ? "mt-3 ml-4 space-y-2" : "mt-2 ml-4 space-y-1"}>
          {node.children.map((child) => (
            <TreeNode key={child.label} node={child} depth={depth + 1} searching={searching} />
          ))}

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

// ─── Politician card ────────────────────────────────────────────────────────
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
      href={profilePath(politician.id)}
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

// ─── Smart search parsing ───────────────────────────────────────────────────
// Pulls a state out of the query (full name, 2-letter code, or ZIP), leaving the
// rest as free-text tokens matched against name / office / party.
//
// To avoid greedily eating personal names ("Georgia Brown", "Virginia Johnson"), a
// full state name or 2-letter code is treated as a location ONLY when every other
// token is itself a location-safe word (an office/branch/party term). A ZIP code is
// always unambiguous, so it is always extracted.
const LOCATION_SAFE_TOKENS = new Set([
  // office / branch terms
  "senate", "senator", "senators", "house", "representative", "representatives",
  "rep", "reps", "congress", "congressional", "governor", "lieutenant", "lt",
  "mayor", "council", "councilmember", "alderman", "aldermen", "sheriff",
  "attorney", "general", "ag", "justice", "court", "courts", "supreme", "county",
  "commissioner", "commissioners", "board", "school", "district", "districts",
  "state", "federal", "local", "assembly", "delegate", "delegates", "treasurer",
  "comptroller", "secretary", "president", "vice", "cabinet", "executive",
  "legislative", "judicial", "branch", "office",
  // party terms
  "democrat", "democratic", "republican", "independent", "libertarian", "green", "party",
  // connectives
  "of", "from", "the", "for", "and",
]);

function parseSearch(raw: string): { stateCode: string | null; textTokens: string[] } {
  const trimmed = raw.trim();
  if (!trimmed) return { stateCode: null, textTokens: [] };

  let tokens = trimmed.split(/\s+/);
  let stateCode: string | null = null;

  // Are all tokens NOT in `used` location-safe? (i.e. safe to read the rest as a location)
  const remainderIsSafe = (used: Set<number>) =>
    tokens.every((t, i) => used.has(i) || LOCATION_SAFE_TOKENS.has(t.toLowerCase()));

  // 1) ZIP — always unambiguous, always extracted.
  const zipIdx = tokens.findIndex((t) => /^\d{5}$/.test(t));
  if (zipIdx !== -1) {
    const code = zipToState(tokens[zipIdx]);
    if (code) {
      stateCode = code;
      tokens.splice(zipIdx, 1);
    }
  }

  // 2) Full state name (possibly multi-word), only if the remainder is location-safe.
  if (!stateCode) {
    const lowerTokens = tokens.map((t) => t.toLowerCase());
    // Longest names first so "West Virginia" wins over "Virginia".
    const names = Object.entries(US_STATES).sort(
      (a, b) => b[1].split(" ").length - a[1].split(" ").length
    );
    for (const [code, name] of names) {
      const nameToks = name.toLowerCase().split(" ");
      for (let i = 0; i + nameToks.length <= lowerTokens.length; i++) {
        if (nameToks.every((nt, j) => lowerTokens[i + j] === nt)) {
          const used = new Set<number>();
          for (let j = 0; j < nameToks.length; j++) used.add(i + j);
          if (remainderIsSafe(used)) {
            stateCode = code;
            tokens = tokens.filter((_, idx) => !used.has(idx));
          }
          break;
        }
      }
      if (stateCode) break;
    }
  }

  // 3) Standalone 2-letter code, only if the remainder is location-safe.
  if (!stateCode) {
    for (let i = 0; i < tokens.length; i++) {
      if (tokens[i].length !== 2) continue;
      const code = resolveStateToken(tokens[i]);
      if (code && remainderIsSafe(new Set([i]))) {
        stateCode = code;
        tokens.splice(i, 1);
        break;
      }
    }
  }

  return { stateCode, textTokens: tokens.filter(Boolean) };
}

// ─── Main component ─────────────────────────────────────────────────────────
export default function DirectoryClient() {
  const [politicians, setPoliticians] = useState<Politician[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [party, setParty] = useState("All");
  const [stateFilter, setStateFilter] = useState("");
  const [level, setLevel] = useState("All");

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchAllPoliticians();
        setPoliticians(data);
      } catch (e) {
        console.error("Failed to load politicians:", e);
        setError("Could not connect to the database. Please try again later.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const parties = useMemo(
    () => ["All", ...Array.from(new Set(politicians.map((p) => p.party || "Unknown").filter(Boolean))).sort()],
    [politicians]
  );

  const parsed = useMemo(() => parseSearch(search), [search]);
  const effectiveState = stateFilter || parsed.stateCode;
  const levelRoot = level === "All" ? null : LEVEL_ROOT[level];

  const filtered = useMemo(() => {
    return politicians.filter((p) => {
      if (effectiveState) {
        // Prefer the structured state column; fall back to a precise office-token
        // match only while the column is still being backfilled.
        const ok = p.state
          ? p.state === effectiveState
          : officeMatchesState(p.current_office || "", effectiveState);
        if (!ok) return false;
      }
      if (party !== "All" && (p.party || "Unknown") !== party) return false;
      if (levelRoot && politicianLevelRoot(p) !== levelRoot) return false;
      if (parsed.textTokens.length > 0) {
        const hay = `${p.full_name} ${p.current_office || ""} ${p.party || ""}`.toLowerCase();
        if (!parsed.textTokens.every((t) => hay.includes(t.toLowerCase()))) return false;
      }
      return true;
    });
  }, [politicians, effectiveState, party, levelRoot, parsed.textTokens]);

  const tree = useMemo(() => buildTree(filtered), [filtered]);
  const total = filtered.length;

  const searching = Boolean(search.trim() || party !== "All" || stateFilter || level !== "All");
  const activeFilterCount =
    (party !== "All" ? 1 : 0) + (stateFilter ? 1 : 0) + (level !== "All" ? 1 : 0);

  return (
    <div className="min-h-screen bg-[var(--color-official-bg)] text-[var(--color-official-text)]">
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
        <div className="mb-10">
          <h1 className="text-4xl md:text-5xl font-extrabold mb-3 bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-500 dark:from-blue-400 dark:to-indigo-300">
            Government Directory
          </h1>
          <p className="text-[var(--color-official-text-muted)] text-lg">
            The full structure of U.S. government — federal, state, and local — as a browsable map.
          </p>
        </div>

        {/* Search + toggleable filters */}
        <div className="mb-8 premium-card p-4 space-y-3">
          <div className="flex gap-3 items-center">
            <input
              type="text"
              placeholder="Search by name, office, party, state, or ZIP code…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 bg-transparent border-b border-[var(--color-official-border)] focus:border-[var(--color-official-link)] px-2 py-2 text-base focus:outline-none transition-colors"
            />
            <button
              onClick={() => setShowFilters((s) => !s)}
              className={`px-4 py-2 rounded-full text-xs font-bold uppercase tracking-wider border transition-all cursor-pointer shrink-0
                ${
                  showFilters || activeFilterCount > 0
                    ? "bg-[var(--color-official-link)] text-white border-[var(--color-official-link)]"
                    : "border-[var(--color-official-border)] text-[var(--color-official-text-muted)] hover:border-[var(--color-official-link)]"
                }`}
            >
              Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
            </button>
          </div>

          {/* Detected-state hint from the smart search */}
          {parsed.stateCode && !stateFilter && (
            <p className="text-xs text-[var(--color-official-text-muted)]">
              Matched location: <strong className="text-[var(--color-official-text)]">{US_STATES[parsed.stateCode]}</strong>
            </p>
          )}

          {showFilters && (
            <div className="pt-3 border-t border-[var(--color-official-border)] space-y-4">
              {/* Level */}
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-official-text-muted)] w-16">Level</span>
                {["All", "Federal", "State", "Local"].map((lv) => (
                  <FilterChip key={lv} label={lv} active={level === lv} onClick={() => setLevel(lv)} />
                ))}
              </div>

              {/* Party */}
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-official-text-muted)] w-16">Party</span>
                {parties.map((p) => (
                  <FilterChip key={p} label={p} active={party === p} onClick={() => setParty(p)} />
                ))}
              </div>

              {/* State */}
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-official-text-muted)] w-16">State</span>
                <select
                  value={stateFilter}
                  onChange={(e) => setStateFilter(e.target.value)}
                  className="bg-[var(--color-official-bg)] border border-[var(--color-official-border)] rounded-full px-3 py-1 text-xs focus:border-[var(--color-official-link)] focus:outline-none cursor-pointer"
                >
                  <option value="">All states</option>
                  {Object.entries(US_STATES).map(([code, name]) => (
                    <option key={code} value={code}>
                      {name}
                    </option>
                  ))}
                </select>
                {activeFilterCount > 0 && (
                  <button
                    onClick={() => {
                      setParty("All");
                      setStateFilter("");
                      setLevel("All");
                    }}
                    className="text-xs text-[var(--color-official-link)] hover:underline ml-2"
                  >
                    Clear filters
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

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
              {searching && <> matching your search</>}
            </p>

            <div className="space-y-3" key={searching ? "searching" : "browsing"}>
              {tree.map((branch) => (
                <TreeNode key={branch.label} node={branch} depth={0} searching={searching} />
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border transition-all cursor-pointer
        ${
          active
            ? "bg-[var(--color-official-link)] text-white border-[var(--color-official-link)]"
            : "border-[var(--color-official-border)] text-[var(--color-official-text-muted)] hover:border-[var(--color-official-link)]"
        }`}
    >
      {label}
    </button>
  );
}
