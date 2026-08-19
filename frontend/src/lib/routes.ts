import { isUuid } from './ids';

export function profilePath(id: string, tab?: string): string {
  if (!isUuid(id)) return `/${encodeURIComponent(id)}`;
  const params = new URLSearchParams({ id });
  if (tab) params.set('tab', tab);
  return `/profile?${params.toString()}`;
}

export function votingComparisonPath(profileId: string, peerId: string): string {
  if (!isUuid(profileId) || !isUuid(peerId) || profileId === peerId) {
    return profilePath(profileId, 'votes');
  }
  const params = new URLSearchParams({
    id: profileId,
    tab: 'votes',
    compare: peerId,
  });
  return `/profile?${params.toString()}`;
}
