const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export interface Politician {
  id: number;
  first_name: string;
  middle_name: string | null;
  last_name: string;
  full_name: string;
  state: string;
  district: string | null;
  chamber: string;
  bioguide_id: string | null;
  in_office: boolean;
  photo_url: string | null;
  party_history: Array<{ party: string; start_date: string | null; end_date: string | null }> | null;
}

export interface PoliticianList {
  items: Politician[];
  total: number;
  page: number;
  per_page: number;
}

export async function fetchPoliticians(params?: {
  page?: number;
  state?: string;
  chamber?: string;
  search?: string;
}): Promise<PoliticianList> {
  const searchParams = new URLSearchParams();
  if (params?.page) searchParams.set("page", String(params.page));
  if (params?.state) searchParams.set("state", params.state);
  if (params?.chamber) searchParams.set("chamber", params.chamber);
  if (params?.search) searchParams.set("search", params.search);

  const res = await fetch(`${API_BASE}/api/politicians?${searchParams}`);
  if (!res.ok) throw new Error("Failed to fetch politicians");
  return res.json();
}

export async function fetchPolitician(id: number): Promise<Politician> {
  const res = await fetch(`${API_BASE}/api/politicians/${id}`);
  if (!res.ok) throw new Error("Politician not found");
  return res.json();
}

export interface VotingRecord {
  id: number;
  politician_id: number;
  roll_call_number: number;
  congress: number;
  session: number;
  chamber: string;
  bill_id: string | null;
  bill_title: string | null;
  bill_type: string | null;
  bill_number: string | null;
  vote: string;
  vote_date: string | null;
  issue_area: string | null;
  source_name: string;
  source_record_id: string;
}

export interface IdeologyScore {
  id: number;
  politician_id: number;
  congress: number;
  chamber: string;
  dw_nominate_dim1: number | null;
  dw_nominate_dim2: number | null;
  source_name: string;
}

export interface Contribution {
  id: number;
  donor_name: string;
  donor_type: string;
  recipient_name: string;
  committee_id: string | null;
  amount: number;
  date: string | null;
  election_cycle: number | null;
  employer: string | null;
  occupation: string | null;
  location: string | null;
  source_name: string;
  source_record_id: string;
}

export interface ContributionSummary {
  total_amount: number;
  total_count: number;
  by_cycle: Record<string, number>;
  by_donor_type: Record<string, number>;
}

export interface LobbyingRecord {
  id: number;
  lda_id: string;
  registrant_name: string;
  client_name: string | null;
  lobbyist_name: string | null;
  issue_area: string | null;
  issue_text: string | null;
  amount: number | null;
  report_quarter: string | null;
  filing_type: string | null;
  government_entities_lobbied: string | null;
  source_xml_url: string | null;
  source_name: string;
  source_record_id: string;
}

export interface LobbyingSummary {
  total_amount: number;
  total_count: number;
  by_issue_area: Record<string, number>;
  by_quarter: Record<string, number>;
}

export interface FinancialDisclosure {
  id: number;
  politician_id: number;
  filing_year: number | null;
  filing_type: string | null;
  asset_name: string | null;
  asset_type: string | null;
  transaction_type: string | null;
  amount_range_low: number | null;
  amount_range_high: number | null;
  notification_date: string | null;
  source_url: string | null;
  ticker: string | null;
  source_name: string;
  source_record_id: string;
}

export interface FinancialDisclosureSummary {
  total_count: number;
  by_ticker: Record<string, number>;
  by_transaction_type: Record<string, number>;
  by_year: Record<string, number>;
}

export interface GovernmentContract {
  id: number;
  award_id: string;
  recipient_name: string;
  awarding_agency: string | null;
  amount: number | null;
  award_date: string | null;
  description: string | null;
  naics_code: string | null;
  place_of_performance: string | null;
  source_name: string;
  source_record_id: string;
}

export interface Organization {
  id: number;
  name: string;
  type: string;
  fec_id: string | null;
  opensecrets_id: string | null;
  source_name: string;
  source_record_id: string;
}

export interface FlowNode {
  id: string;
  label: string;
  type: string;
}

export interface FlowLink {
  source: string;
  target: string;
  weight: number;
  count: number;
}

export interface OrganizationFlow {
  organization_id: number;
  organization_name: string;
  nodes: FlowNode[];
  links: FlowLink[];
}

export async function fetchPoliticianVoting(
  id: number,
  congress?: number,
  limit: number = 50
): Promise<VotingRecord[]> {
  const params = new URLSearchParams();
  if (congress) params.set("congress", String(congress));
  params.set("limit", String(limit));
  const res = await fetch(`${API_BASE}/api/politicians/${id}/voting?${params}`);
  if (!res.ok) throw new Error("Failed to fetch voting records");
  return res.json();
}

export async function fetchPoliticianContributions(
  id: number,
  limit: number = 50
): Promise<Contribution[]> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const res = await fetch(`${API_BASE}/api/politicians/${id}/contributions?${params}`);
  if (!res.ok) throw new Error("Failed to fetch contributions");
  return res.json();
}

export async function fetchContributionSummary(
  politicianId?: number,
  electionCycle?: number
): Promise<ContributionSummary> {
  const params = new URLSearchParams();
  if (politicianId) params.set("politician_id", String(politicianId));
  if (electionCycle) params.set("election_cycle", String(electionCycle));
  const res = await fetch(`${API_BASE}/api/contributions/summary?${params}`);
  if (!res.ok) throw new Error("Failed to fetch contribution summary");
  return res.json();
}

export async function fetchIdeologyScores(
  politicianId: number,
  congress?: number
): Promise<IdeologyScore[]> {
  const params = new URLSearchParams();
  params.set("politician_id", String(politicianId));
  if (congress) params.set("congress", String(congress));
  const res = await fetch(`${API_BASE}/api/voting/ideology-scores?${params}`);
  if (!res.ok) throw new Error("Failed to fetch ideology scores");
  return res.json();
}

export async function fetchPoliticianFinancials(
  id: number,
  limit: number = 50
): Promise<FinancialDisclosure[]> {
  const res = await fetch(`${API_BASE}/api/politicians/${id}/financials?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch financial disclosures");
  return res.json();
}

export async function fetchOrganizations(
  params?: { page?: number; name?: string; type?: string }
): Promise<{ items: Organization[]; total: number; page: number; per_page: number }> {
  const search = new URLSearchParams();
  if (params?.page) search.set("page", String(params.page));
  if (params?.name) search.set("name", params.name);
  if (params?.type) search.set("type", params.type);
  const res = await fetch(`${API_BASE}/api/organizations?${search}`);
  if (!res.ok) throw new Error("Failed to fetch organizations");
  return res.json();
}

export async function fetchOrganization(id: number): Promise<Organization> {
  const res = await fetch(`${API_BASE}/api/organizations/${id}`);
  if (!res.ok) throw new Error("Organization not found");
  return res.json();
}

export async function fetchOrganizationFlow(
  id: number,
  limit: number = 50
): Promise<OrganizationFlow> {
  const res = await fetch(`${API_BASE}/api/organizations/${id}/flow?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch organization flow");
  return res.json();
}
