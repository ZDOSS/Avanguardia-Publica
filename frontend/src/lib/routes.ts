const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function profilePath(id: string): string {
  if (!UUID_RE.test(id)) return `/${encodeURIComponent(id)}`;
  return `/profile?id=${encodeURIComponent(id)}`;
}
