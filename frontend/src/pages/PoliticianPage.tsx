import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  fetchPolitician,
  fetchPoliticianVoting,
  fetchPoliticianContributions,
  fetchIdeologyScores,
  fetchContributionSummary,
  fetchPoliticianFinancials,
  fetchPoliticianTags,
  type VotingRecord,
  type Contribution,
  type FinancialDisclosure,
  type Tag,
} from "../lib/api";
import { chamberLabel } from "../lib/politician";
import { useState } from "react";
import DonorChart from "../components/DonorChart";
import { ProvenanceBadge, ThirdPartyDisclaimer } from "../components/ProvenanceBadge";

function VoteBadge({ vote }: { vote: string }) {
  const colors: Record<string, string> = {
    yea: "bg-green-100 text-green-800",
    nay: "bg-red-100 text-red-800",
    present: "bg-yellow-100 text-yellow-800",
    not_voting: "bg-gray-100 text-gray-800",
  };
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded ${colors[vote] || "bg-gray-100 text-gray-800"}`}>
      {vote.replaceAll("_", " ")}
    </span>
  );
}

function IdeologyBar({ dim1 }: { dim1: number | null }) {
  if (dim1 === null) return <span className="text-sm text-gray-500">No data</span>;
  const pct = Math.round(((dim1 + 1) / 2) * 100);
  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>Liberal</span>
        <span>Conservative</span>
      </div>
      <div className="h-3 bg-gradient-to-r from-blue-400 via-gray-200 to-red-400 rounded-full relative">
        <div
          className="absolute top-0 w-1.5 h-3 bg-black rounded-full"
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="text-center text-xs text-gray-500 mt-1">{dim1.toFixed(3)}</div>
    </div>
  );
}

export default function PoliticianPage() {
  const { id } = useParams<{ id: string }>();
  const politicianId = Number(id);
  const [votingLimit] = useState(50);
  const [contribLimit] = useState(50);

  const { data: politician, isLoading: pLoading, error: pError } = useQuery({
    queryKey: ["politician", id],
    queryFn: () => fetchPolitician(politicianId),
    enabled: !!id,
  });

  const { data: votingRecords, isLoading: vLoading } = useQuery({
    queryKey: ["politician-voting", id, votingLimit],
    queryFn: () => fetchPoliticianVoting(politicianId, undefined, votingLimit),
    enabled: !!id,
  });

  const { data: ideologyScores, isLoading: iLoading } = useQuery({
    queryKey: ["politician-ideology", id],
    queryFn: () => fetchIdeologyScores(politicianId),
    enabled: !!id,
  });

  const { data: contributions, isLoading: cLoading } = useQuery({
    queryKey: ["politician-contributions", id, contribLimit],
    queryFn: () => fetchPoliticianContributions(politicianId, contribLimit),
    enabled: !!id,
  });

  const { data: contribSummary } = useQuery({
    queryKey: ["contribution-summary", politicianId],
    queryFn: () => fetchContributionSummary(politicianId),
    enabled: !!id,
  });

  const { data: financials, isLoading: finLoading } = useQuery({
    queryKey: ["politician-financials", id],
    queryFn: () => fetchPoliticianFinancials(politicianId, 50),
    enabled: !!id,
  });

  const { data: tagsData } = useQuery({
    queryKey: ["politician-tags", id],
    queryFn: () => fetchPoliticianTags(politicianId),
    enabled: !!id,
  });

  if (pLoading) return <p className="text-gray-500">Loading...</p>;
  if (pError || !politician) return <p className="text-red-500">Politician not found.</p>;

  const party = Array.isArray(politician.party_history) && politician.party_history[0]?.party;
  const latestIdeology = ideologyScores && ideologyScores[0];

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start gap-4 sm:gap-6 mb-8">
        {politician.photo_url && (
          <img
            src={politician.photo_url}
            alt={politician.full_name}
            className="w-24 h-24 sm:w-32 sm:h-32 rounded-full object-cover border-4 border-gray-200"
          />
        )}
        <div>
          <h2 className="text-2xl sm:text-3xl font-bold">{politician.full_name}</h2>
          <p className="text-lg text-gray-600">
            {chamberLabel(politician.chamber, politician.country_code)}
            {" · "}{politician.state}
            {politician.district && `-${politician.district}`}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            {politician.country_code === "CA"
              ? "Canada"
              : politician.country_code === "US"
                ? "United States"
                : politician.country_code}
            {" · "}
            {politician.jurisdiction_level}
          </p>
          {party && <span className="text-sm bg-blue-100 text-blue-800 rounded px-3 py-1 mt-2 inline-block">{party}</span>}
          {politician.bioguide_id && (
            <p className="text-xs text-gray-400 mt-1">Bioguide: {politician.bioguide_id}</p>
          )}
          {tagsData && tagsData.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {tagsData.tags.map((tag: Tag) => (
                <span
                  key={tag.id}
                  className="text-xs bg-amber-100 text-amber-900 rounded px-2 py-0.5"
                  title={tag.description ?? undefined}
                >
                  {tag.name}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-8 lg:grid-cols-3">
        {/* Bio */}
        <section className="border rounded-lg p-4 bg-white">
          <h3 className="text-lg font-semibold mb-3">Bio</h3>
          <dl className="text-sm space-y-2">
            <div>
              <dt className="text-gray-500">First Name</dt>
              <dd>{politician.first_name}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Last Name</dt>
              <dd>{politician.last_name}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Status</dt>
              <dd>{politician.in_office ? "In Office" : "Out of Office"}</dd>
            </div>
          </dl>
        </section>

        {/* Ideology Score */}
        <section className="border rounded-lg p-4 bg-white">
          <h3 className="text-lg font-semibold mb-3">Ideology Score (DW-NOMINATE)</h3>
          {iLoading ? (
            <p className="text-sm text-gray-500">Loading...</p>
          ) : latestIdeology ? (
            <div className="space-y-4">
              <IdeologyBar dim1={latestIdeology.dw_nominate_dim1} />
              <div className="text-xs text-gray-500">
                Congress {latestIdeology.congress} · {latestIdeology.chamber}
              </div>
              <div className="text-xs text-gray-400">
                Dim 2: {latestIdeology.dw_nominate_dim2?.toFixed(3) ?? "N/A"}
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">No ideology data available.</p>
          )}
        </section>

        {/* Campaign Finance Summary */}
        <section className="border rounded-lg p-4 bg-white">
          <h3 className="text-lg font-semibold mb-3">Campaign Finance</h3>
          {contribSummary ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Total Contributions</span>
                <span className="font-semibold">${contribSummary.total_amount.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Count</span>
                <span className="font-semibold">{contribSummary.total_count}</span>
              </div>
              {Object.entries(contribSummary.by_donor_type).map(([type, amount]) => (
                <div key={type} className="flex justify-between">
                  <span className="text-gray-500 capitalize">{type.replaceAll("_", " ")}</span>
                  <span>${amount.toLocaleString()}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">No contribution data available.</p>
          )}
        </section>
      </div>

      {/* Campaign Finance Dashboard */}
      <section className="mt-8 border rounded-lg p-4 bg-white">
        <h3 className="text-lg font-semibold mb-4">Campaign Finance Dashboard</h3>
        {contribSummary ? (
          <DonorChart
            byDonorType={contribSummary.by_donor_type}
            byCycle={contribSummary.by_cycle}
          />
        ) : (
          <p className="text-sm text-gray-500">No contribution data available.</p>
        )}
      </section>

      {/* Voting Records */}
      <section className="mt-8 border rounded-lg p-4 bg-white">
        <h3 className="text-lg font-semibold mb-4">Recent Voting Records</h3>
        {vLoading ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : votingRecords && votingRecords.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b">
                <tr className="text-left text-gray-500">
                  <th className="pb-2 pr-4">Date</th>
                  <th className="pb-2 pr-4">Congress</th>
                  <th className="pb-2 pr-4">Roll Call</th>
                  <th className="pb-2 pr-4">Bill</th>
                  <th className="pb-2 pr-4">Vote</th>
                  <th className="pb-2">Issue</th>
                </tr>
              </thead>
              <tbody>
                {votingRecords.map((r: VotingRecord) => (
                  <tr key={r.id} className="border-b last:border-b-0">
                    <td className="py-2 pr-4 text-gray-600">{r.vote_date ?? "—"}</td>
                    <td className="py-2 pr-4">{r.congress}</td>
                    <td className="py-2 pr-4">{r.roll_call_number}</td>
                    <td className="py-2 pr-4">
                      {r.bill_number ? (
                        <span className="font-medium">{r.bill_type} {r.bill_number}</span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="py-2 pr-4"><VoteBadge vote={r.vote} /></td>
                    <td className="py-2 text-gray-600">{r.issue_area ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No voting records available.</p>
        )}
      </section>

      {/* Contributions */}
      <section className="mt-8 border rounded-lg p-4 bg-white">
        <h3 className="text-lg font-semibold mb-4">Recent Contributions</h3>
        {cLoading ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : contributions && contributions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b">
                <tr className="text-left text-gray-500">
                  <th className="pb-2 pr-4">Date</th>
                  <th className="pb-2 pr-4">Donor</th>
                  <th className="pb-2 pr-4">Type</th>
                  <th className="pb-2 pr-4">Amount</th>
                  <th className="pb-2 pr-4">Employer</th>
                  <th className="pb-2">Location</th>
                </tr>
              </thead>
              <tbody>
                {contributions.map((c: Contribution) => (
                  <tr key={c.id} className="border-b last:border-b-0">
                    <td className="py-2 pr-4 text-gray-600">{c.date ?? "—"}</td>
                    <td className="py-2 pr-4 font-medium">{c.donor_name}</td>
                    <td className="py-2 pr-4 capitalize">{c.donor_type.replaceAll("_", " ")}</td>
                    <td className="py-2 pr-4">${c.amount.toLocaleString()}</td>
                    <td className="py-2 pr-4 text-gray-600">{c.employer ?? "—"}</td>
                    <td className="py-2 text-gray-600">{c.location ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No contribution data available.</p>
        )}
      </section>

      {/* Stock Trades & Financial Disclosures */}
      <section className="mt-8 border rounded-lg p-4 bg-white">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Stock Trades & Financial Disclosures</h3>
          <div className="flex gap-1">
            <ProvenanceBadge source="house_clerk" />
            <ProvenanceBadge source="quiver_quant" />
          </div>
        </div>
        {finLoading ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : financials && financials.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b">
                <tr className="text-left text-gray-500">
                  <th className="pb-2 pr-4">Date</th>
                  <th className="pb-2 pr-4">Asset</th>
                  <th className="pb-2 pr-4">Ticker</th>
                  <th className="pb-2 pr-4">Type</th>
                  <th className="pb-2 pr-4">Amount Range</th>
                  <th className="pb-2">Source</th>
                </tr>
              </thead>
              <tbody>
                {financials.map((f: FinancialDisclosure) => (
                  <tr key={f.id} className="border-b last:border-b-0">
                    <td className="py-2 pr-4 text-gray-600">{f.notification_date ?? "—"}</td>
                    <td className="py-2 pr-4 font-medium">{f.asset_name ?? "—"}</td>
                    <td className="py-2 pr-4">{f.ticker ?? "—"}</td>
                    <td className="py-2 pr-4 capitalize">{f.transaction_type ?? "—"}</td>
                    <td className="py-2 pr-4 text-gray-600">
                      {f.amount_range_low != null && f.amount_range_high != null
                        ? `$${f.amount_range_low.toLocaleString()} – $${f.amount_range_high.toLocaleString()}`
                        : "—"}
                    </td>
                    <td className="py-2">
                      <ProvenanceBadge source={f.source_name} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No financial disclosures on file.</p>
        )}
      </section>

      {/* Data Provenance */}
      <div className="mt-8 text-xs text-gray-400 text-center">
        <p>
          Data sourced from government APIs (Congress.gov, FEC, USAspending.gov, Senate LDA, House Clerk, SEC EDGAR)
          and third-party sources (VoteView, OpenSecrets, Quiver Quantitative).
        </p>
        <ThirdPartyDisclaimer />
      </div>
    </div>
  );
}
