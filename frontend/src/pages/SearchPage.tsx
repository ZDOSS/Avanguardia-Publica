import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { searchAll, type SearchResultItem } from "../lib/api";

const ENTITY_LABELS: Record<SearchResultItem["entity_type"], string> = {
  politician: "Politicians",
  organization: "Organizations",
  contribution: "Contributions",
  voting_record: "Voting Records",
};

const ENTITY_ORDER: SearchResultItem["entity_type"][] = [
  "politician",
  "organization",
  "contribution",
  "voting_record",
];

export default function SearchPage() {
  const [params] = useSearchParams();
  const q = params.get("q") || "";

  const { data, isLoading, error } = useQuery({
    queryKey: ["search-page", q],
    queryFn: () => searchAll(q, 50),
    enabled: q.length >= 2,
  });

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Search</h2>
      <p className="text-sm text-gray-600 mb-6">
        Results for <span className="font-semibold">"{q}"</span>
      </p>

      {q.length < 2 && (
        <p className="text-gray-500">Enter at least 2 characters to search.</p>
      )}
      {isLoading && <p className="text-gray-500">Searching...</p>}
      {error && <p className="text-red-500">Search failed.</p>}

      {data && data.items.length === 0 && (
        <p className="text-gray-500">No matches found.</p>
      )}

      {data && data.items.length > 0 && (
        <div className="space-y-8">
          {ENTITY_ORDER.map((entityType) => {
            const matches = data.items.filter((item) => item.entity_type === entityType);
            if (matches.length === 0) return null;
            return (
              <section key={entityType}>
                <h3 className="text-lg font-semibold mb-3 text-gray-700">
                  {ENTITY_LABELS[entityType]}
                  <span className="ml-2 text-sm font-normal text-gray-500">
                    ({matches.length})
                  </span>
                </h3>
                <ul className="divide-y border rounded bg-white">
                  {matches.map((item) => (
                    <li key={`${item.entity_type}:${item.entity_id}`} className="p-3 hover:bg-gray-50">
                      {item.url ? (
                        <Link to={item.url} className="block">
                          <div className="font-medium text-blue-800">{item.title}</div>
                          {item.subtitle && (
                            <div className="text-sm text-gray-600">{item.subtitle}</div>
                          )}
                          <div className="text-xs text-gray-400 mt-1">
                            rank {item.rank.toFixed(3)}
                          </div>
                        </Link>
                      ) : (
                        <div>
                          <div className="font-medium text-gray-800">{item.title}</div>
                          {item.subtitle && (
                            <div className="text-sm text-gray-600">{item.subtitle}</div>
                          )}
                          <div className="text-xs text-gray-400 mt-1">
                            rank {item.rank.toFixed(3)} · deep link not yet available
                          </div>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
