const SOURCE_LABELS: Record<string, { label: string; url: string; disclaimer?: string }> = {
  fec_api: {
    label: "FEC",
    url: "https://api.open.fec.gov/developers/",
    disclaimer: "Federal Election Commission disclosure data",
  },
  congress_gov_api: {
    label: "Congress.gov",
    url: "https://api.congress.gov/",
    disclaimer: "Official U.S. Congress legislative data",
  },
  voteview: {
    label: "VoteView",
    url: "https://voteview.com/",
    disclaimer: "Third-party academic roll-call vote data",
  },
  opensecrets_bulk: {
    label: "OpenSecrets",
    url: "https://www.opensecrets.org/",
    disclaimer: "Third-party campaign finance aggregation",
  },
  senate_lda: {
    label: "Senate LDA",
    url: "https://lda.senate.gov/",
    disclaimer: "Lobbying disclosure filings; subject to filer self-reporting",
  },
  house_clerk: {
    label: "House Clerk",
    url: "https://disclosures-clerk.house.gov/",
    disclaimer: "STOCK Act transaction disclosures; subject to filer self-reporting",
  },
  usaspending: {
    label: "USAspending.gov",
    url: "https://www.usaspending.gov/",
    disclaimer: "Federal contract and grant award data",
  },
  sec_edgar: {
    label: "SEC EDGAR",
    url: "https://www.sec.gov/edgar",
    disclaimer: "Corporate insider Form 4 filings",
  },
  quiver_quant: {
    label: "Quiver Quantitative",
    url: "https://www.quiverquant.com/",
    disclaimer: "Third-party aggregation of congressional trades; not an official source",
  },
};

export function ProvenanceBadge({ source }: { source: string }) {
  const meta = SOURCE_LABELS[source];
  if (!meta) {
    return (
      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
        {source}
      </span>
    );
  }
  return (
    <a
      href={meta.url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded hover:underline"
      title={meta.disclaimer ?? ""}
    >
      {meta.label}
    </a>
  );
}

export function ThirdPartyDisclaimer() {
  return (
    <div className="text-xs text-gray-500 italic mt-1">
      Data sourced from third-party aggregators (VoteView, OpenSecrets, Senate LDA,
      House Clerk, USAspending.gov, SEC EDGAR, Quiver Quantitative) is provided
      "as-is" and may differ from official sources. Always cross-reference with
      the original filing when accuracy is critical.
    </div>
  );
}
