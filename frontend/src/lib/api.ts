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
  party_history: Record<string, unknown> | null;
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
