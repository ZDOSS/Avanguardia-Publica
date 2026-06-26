export const DEFAULT_PROFILE_PAGE_SIZE = 25;

export interface PageResult<T> {
  rows: T[];
  count: number | null;
  hasMore?: boolean;
  page: number;
  pageSize: number;
}

export function pageRange(page: number, pageSize = DEFAULT_PROFILE_PAGE_SIZE) {
  const safePage = Math.max(0, page);
  const from = safePage * pageSize;
  return { from, to: from + pageSize - 1, page: safePage, pageSize };
}

export function hasNextPage<T>(result: PageResult<T>): boolean {
  if (typeof result.hasMore === 'boolean') return result.hasMore;
  if (typeof result.count === 'number') {
    return (result.page + 1) * result.pageSize < result.count;
  }
  return result.rows.length === result.pageSize;
}

export function emptyPage<T>(page = 0, pageSize = DEFAULT_PROFILE_PAGE_SIZE): PageResult<T> {
  return { rows: [], count: 0, page, pageSize };
}
