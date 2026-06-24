import { isUuid } from './ids';

export function profilePath(id: string): string {
  if (!isUuid(id)) return `/${encodeURIComponent(id)}`;
  return `/profile?id=${encodeURIComponent(id)}`;
}
