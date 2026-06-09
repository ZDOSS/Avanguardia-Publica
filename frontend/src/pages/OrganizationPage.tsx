import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchOrganization } from "../lib/api";
import { FollowTheMoney } from "../components/FollowTheMoney";
import { ProvenanceBadge, ThirdPartyDisclaimer } from "../components/ProvenanceBadge";

export default function OrganizationPage() {
  const { id } = useParams<{ id: string }>();
  const orgId = Number(id);

  const { data: org, isLoading, error } = useQuery({
    queryKey: ["organization", id],
    queryFn: () => fetchOrganization(orgId),
    enabled: !!id,
  });

  if (isLoading) return <p className="text-gray-500">Loading...</p>;
  if (error || !org) return <p className="text-red-500">Organization not found.</p>;

  return (
    <div>
      <div className="mb-8">
        <Link to="/" className="text-sm text-blue-600 hover:underline">← Back</Link>
        <h2 className="text-3xl font-bold mt-2">{org.name}</h2>
        <div className="flex items-center gap-2 mt-2">
          <span className="text-sm bg-purple-100 text-purple-800 rounded px-3 py-1 capitalize">
            {org.type.replaceAll("_", " ")}
          </span>
          {org.fec_id && (
            <span className="text-xs bg-gray-100 text-gray-700 rounded px-2 py-0.5">
              FEC: {org.fec_id}
            </span>
          )}
          {org.opensecrets_id && (
            <span className="text-xs bg-gray-100 text-gray-700 rounded px-2 py-0.5">
              OpenSecrets: {org.opensecrets_id}
            </span>
          )}
          <ProvenanceBadge source={org.source_name} />
        </div>
      </div>

      <section className="border rounded-lg p-4 bg-white mb-8">
        <h3 className="text-lg font-semibold mb-4">Follow the Money</h3>
        <p className="text-sm text-gray-600 mb-4">
          Visualize the downstream flow of contributions from this organization to
          candidates and committees, based on aggregated FEC and OpenSecrets data.
        </p>
        <FollowTheMoney organizationId={orgId} />
      </section>

      <ThirdPartyDisclaimer />
    </div>
  );
}
