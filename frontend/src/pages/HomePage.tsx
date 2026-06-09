import { useQuery } from "@tanstack/react-query";
import { fetchPoliticians, Politician } from "../lib/api";
import { useState } from "react";
import { Link } from "react-router-dom";

// US states plus Canadian provinces/territories. The state filter is
// jurisdiction-aware: when country_code is "CA" the dropdown lists
// provinces, otherwise it lists US states.
const US_STATES =
  "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(
    " ",
  );
const CA_PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"];

function chamberLabel(p: Politician): string {
  switch (p.chamber) {
    case "senate":
      return "Senator";
    case "house":
      return p.country_code === "CA" ? "MP" : "Representative";
    case "state_senate":
      return "State Senator";
    case "state_house":
      return "State Representative";
    case "governor":
      return "Governor";
    default:
      return p.chamber;
  }
}

export default function HomePage() {
  const [search, setSearch] = useState("");
  const [country, setCountry] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [state, setState] = useState("");
  const [chamber, setChamber] = useState("");
  const [page, setPage] = useState(1);

  // Reset state/province filter whenever the country changes so the
  // user doesn't get stuck filtering "CA" states by a US postal code.
  function setCountryAndResetState(value: string) {
    setCountry(value);
    setState("");
    setPage(1);
  }

  const { data, isLoading, error } = useQuery({
    queryKey: ["politicians", { page, country, jurisdiction, state, chamber, search }],
    queryFn: () =>
      fetchPoliticians({
        page,
        country_code: country || undefined,
        jurisdiction_level: jurisdiction || undefined,
        state: state || undefined,
        chamber: chamber || undefined,
        search: search || undefined,
      }),
  });

  const stateOptions = country === "CA" ? CA_PROVINCES : US_STATES;
  const isCanada = country === "CA";

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold mb-4">Politicians</h2>
        <div className="flex gap-3 flex-wrap">
          <input
            type="text"
            placeholder="Search by name..."
            className="border rounded px-3 py-2 w-full sm:w-64"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
          <select
            className="border rounded px-3 py-2 w-full sm:w-auto"
            value={country}
            onChange={(e) => setCountryAndResetState(e.target.value)}
          >
            <option value="">All Countries</option>
            <option value="US">United States</option>
            <option value="CA">Canada</option>
          </select>
          <select
            className="border rounded px-3 py-2 w-full sm:w-auto"
            value={jurisdiction}
            onChange={(e) => {
              setJurisdiction(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All Levels</option>
            {isCanada ? (
              <>
                <option value="federal">Federal</option>
                <option value="provincial">Provincial</option>
                <option value="territorial">Territorial</option>
              </>
            ) : (
              <>
                <option value="federal">Federal</option>
                <option value="state">State</option>
              </>
            )}
          </select>
          <select
            className="border rounded px-3 py-2 w-full sm:w-auto"
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{isCanada ? "All Provinces" : "All States"}</option>
            {stateOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            className="border rounded px-3 py-2 w-full sm:w-auto"
            value={chamber}
            onChange={(e) => {
              setChamber(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All Chambers</option>
            <option value="house">House</option>
            <option value="senate">Senate</option>
            <option value="state_house">State House</option>
            <option value="state_senate">State Senate</option>
            <option value="governor">Governor</option>
          </select>
        </div>
      </div>

      {isLoading && <p className="text-gray-500">Loading...</p>}
      {error && <p className="text-red-500">Error loading data.</p>}

      {data && (
        <>
          <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((p: Politician) => (
              <Link
                key={p.id}
                to={`/politician/${p.id}`}
                className="block border rounded-lg p-4 hover:shadow-md transition bg-white"
              >
                <h3 className="font-semibold text-lg">{p.full_name}</h3>
                <p className="text-sm text-gray-600">
                  {chamberLabel(p)} &middot; {p.state}
                  {p.district && `-${p.district}`}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {p.country_code} · {p.jurisdiction_level}
                </p>
                {p.party_history && (
                  <span className="inline-block mt-1 text-xs bg-gray-100 rounded px-2 py-0.5">
                    {Array.isArray(p.party_history) && p.party_history[0]?.party}
                  </span>
                )}
              </Link>
            ))}
          </div>
          <div className="flex flex-col sm:flex-row sm:justify-center items-center gap-2 sm:gap-4 mt-6">
            <button
              className="w-full sm:w-auto px-4 py-2 border rounded disabled:opacity-50"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </button>
            <span className="py-2 text-sm text-gray-500">
              Page {page} of {Math.ceil(data.total / data.per_page)}
            </span>
            <button
              className="w-full sm:w-auto px-4 py-2 border rounded disabled:opacity-50"
              disabled={page >= Math.ceil(data.total / data.per_page)}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
