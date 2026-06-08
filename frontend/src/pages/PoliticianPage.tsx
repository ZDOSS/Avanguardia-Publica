import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchPolitician } from "../lib/api";

export default function PoliticianPage() {
  const { id } = useParams<{ id: string }>();
  const { data: politician, isLoading, error } = useQuery({
    queryKey: ["politician", id],
    queryFn: () => fetchPolitician(Number(id)),
    enabled: !!id,
  });

  if (isLoading) return <p className="text-gray-500">Loading...</p>;
  if (error || !politician) return <p className="text-red-500">Politician not found.</p>;

  const party = Array.isArray(politician.party_history) && politician.party_history[0]?.party;

  return (
    <div>
      <div className="flex items-start gap-6 mb-8">
        {politician.photo_url && (
          <img
            src={politician.photo_url}
            alt={politician.full_name}
            className="w-32 h-32 rounded-full object-cover border-4 border-gray-200"
          />
        )}
        <div>
          <h2 className="text-3xl font-bold">{politician.full_name}</h2>
          <p className="text-lg text-gray-600">
            {politician.chamber === "senate" ? "Senator" : "Representative"}
            {" · "}{politician.state}
            {politician.district && `-${politician.district}`}
          </p>
          {party && <span className="text-sm bg-blue-100 text-blue-800 rounded px-3 py-1 mt-2 inline-block">{party}</span>}
          {politician.bioguide_id && (
            <p className="text-xs text-gray-400 mt-1">Bioguide: {politician.bioguide_id}</p>
          )}
        </div>
      </div>

      <div className="grid gap-8 md:grid-cols-2">
        <section className="border rounded-lg p-4 bg-white">
          <h3 className="text-lg font-semibold mb-3">Bio</h3>
          <dl className="text-sm space-y-1">
            <dt className="text-gray-500">First Name</dt>
            <dd>{politician.first_name}</dd>
            <dt className="text-gray-500 mt-2">Last Name</dt>
            <dd>{politician.last_name}</dd>
            <dt className="text-gray-500 mt-2">Status</dt>
            <dd>{politician.in_office ? "In Office" : "Out of Office"}</dd>
          </dl>
        </section>

        <section className="border rounded-lg p-4 bg-white">
          <h3 className="text-lg font-semibold mb-3">Data Sources</h3>
          <p className="text-sm text-gray-500">
            Campaign finance, voting records, lobbying, and financial disclosure data
            will be available after data ingestion completes.
          </p>
        </section>
      </div>
    </div>
  );
}
