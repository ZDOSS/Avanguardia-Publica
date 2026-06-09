import { useQuery } from "@tanstack/react-query";
import { fetchOrganizationFlow, type FlowNode, type FlowLink } from "../lib/api";
import { ProvenanceBadge } from "./ProvenanceBadge";

const PALETTE = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4"];

interface FollowTheMoneyProps {
  organizationId: number;
}

export function FollowTheMoney({ organizationId }: FollowTheMoneyProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["org-flow", organizationId],
    queryFn: () => fetchOrganizationFlow(organizationId),
  });

  if (isLoading) return <p className="text-sm text-gray-500">Loading flow data...</p>;
  if (error || !data) return <p className="text-sm text-red-500">Failed to load flow data.</p>;
  if (data.links.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No downstream contribution links found for this organization yet.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-gray-600">
        <span>Sources:</span>
        <ProvenanceBadge source="opensecrets_bulk" />
        <ProvenanceBadge source="fec_api" />
      </div>
      <FlowDiagram nodes={data.nodes} links={data.links} />
      <div className="text-xs text-gray-500">
        Showing top {data.links.length} downstream flows from{" "}
        <strong>{data.organization_name}</strong> based on FEC/OpenSecrets contribution data.
      </div>
    </div>
  );
}

function FlowDiagram({ nodes, links }: { nodes: FlowNode[]; links: FlowLink[] }) {
  const orgNodes = nodes.filter((n) => n.type === "organization");
  const recipientNodes = nodes.filter((n) => n.type !== "organization");
  const totalWeight = links.reduce((s, l) => s + l.weight, 0) || 1;
  const maxWeight = Math.max(...links.map((l) => l.weight), 1);

  return (
    <div className="border rounded-lg p-4 bg-gray-50">
      <div className="flex flex-col gap-2">
        {orgNodes.map((org) => (
          <div key={org.id} className="flex items-center gap-3">
            <div className="w-48 text-sm font-semibold text-blue-900 truncate">
              {org.label}
            </div>
            <div className="flex-1 space-y-1">
              {links
                .filter((l) => l.source === org.id)
                .slice(0, 10)
                .map((l, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span
                      className="inline-block h-3 rounded"
                      style={{
                        width: `${Math.max(2, (l.weight / maxWeight) * 200)}px`,
                        backgroundColor: PALETTE[i % PALETTE.length],
                      }}
                    />
                    <span className="font-medium">{l.target.replace("recipient:", "")}</span>
                    <span className="text-gray-500">
                      ${l.weight.toLocaleString()} ({l.count} contributions, {((l.weight / totalWeight) * 100).toFixed(1)}%)
                    </span>
                  </div>
                ))}
            </div>
          </div>
        ))}
        {recipientNodes.length === 0 && (
          <p className="text-sm text-gray-500 italic">No recipient breakdown available.</p>
        )}
      </div>
    </div>
  );
}
