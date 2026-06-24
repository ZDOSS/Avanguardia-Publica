import { isUuid } from './ids';

export function profilePath(id: string, tab?: string): string {
  if (!isUuid(id)) return `/${encodeURIComponent(id)}`;
  const params = new URLSearchParams({ id });
  if (tab) params.set('tab', tab);
  return `/profile?${params.toString()}`;
}
