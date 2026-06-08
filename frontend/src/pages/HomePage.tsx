import { useQuery } from "@tanstack/react-query";
import { fetchPoliticians, Politician } from "../lib/api";
import { useState } from "react";

export default function HomePage() {
  const [search, setSearch] = useState("");
  const [state, setState] = useState("");
  const [chamber, setChamber] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["politicians", { page, state, chamber, search }],
    queryFn: () => fetchPoliticians({ page, state: state || undefined, chamber: chamber || undefined, search: search || undefined }),
  });

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold mb-4">US Politicians</h2>
        <div className="flex gap-3 flex-wrap">
          <input
            type="text"
            placeholder="Search by name..."
            className="border rounded px-3 py-2 w-64"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
          <select
            className="border rounded px-3 py-2"
            value={state}
            onChange={(e) => { setState(e.target.value); setPage(1); }}
          >
            <option value="">All States</option>
            {"AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(" ").map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            className="border rounded px-3 py-2"
            value={chamber}
            onChange={(e) => { setChamber(e.target.value); setPage(1); }}
          >
            <option value="">All Chambers</option>
            <option value="house">House</option>
            <option value="senate">Senate</option>
          </select>
        </div>
      </div>

      {isLoading && <p className="text-gray-500">Loading...</p>}
      {error && <p className="text-red-500">Error loading data.</p>}

      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((p: Politician) => (
              <a
                key={p.id}
                href={`/politician/${p.id}`}
                className="block border rounded-lg p-4 hover:shadow-md transition bg-white"
              >
                <h3 className="font-semibold text-lg">{p.full_name}</h3>
                <p className="text-sm text-gray-600">
                  {p.chamber === "senate" ? "Senator" : "Representative"} &middot; {p.state}
                  {p.district && `-${p.district}`}
                </p>
                {p.party_history && (
                  <span className="inline-block mt-1 text-xs bg-gray-100 rounded px-2 py-0.5">
                    {Array.isArray(p.party_history) && p.party_history[0]?.party}
                  </span>
                )}
              </a>
            ))}
          </div>
          <div className="flex justify-center gap-4 mt-6">
            <button
              className="px-4 py-2 border rounded disabled:opacity-50"
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
            >
              Previous
            </button>
            <span className="py-2 text-sm text-gray-500">
              Page {page} of {Math.ceil(data.total / data.per_page)}
            </span>
            <button
              className="px-4 py-2 border rounded disabled:opacity-50"
              disabled={page >= Math.ceil(data.total / data.per_page)}
              onClick={() => setPage(p => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
