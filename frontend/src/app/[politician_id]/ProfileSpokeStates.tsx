import { hasNextPage, type PageResult } from '@/lib/pagination';

export function formatDate(value: string | null | undefined): string {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function SectionHeading({ title, meta }: { title: string; meta?: string }) {
  return (
    <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
      <h2 className="text-xs font-bold uppercase tracking-widest text-[var(--color-official-text-muted)]">{title}</h2>
      {meta && <p className="text-xs text-[var(--color-official-text-muted)]">{meta}</p>}
    </div>
  );
}

export function LoadingBlock() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="h-14 premium-card bg-[var(--color-official-bg-alt)]" />
      <div className="h-40 premium-card bg-[var(--color-official-bg-alt)]" />
      <div className="h-28 premium-card bg-[var(--color-official-bg-alt)]" />
    </div>
  );
}

export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="p-8 premium-card text-center">
      <p className="mb-4 font-semibold text-[var(--color-warning-badge)]">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-full border border-[var(--color-official-border)] px-4 py-2 text-sm font-bold text-[var(--color-official-link)] transition-colors hover:border-[var(--color-official-link)] cursor-pointer"
      >
        Retry
      </button>
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="p-8 premium-card text-center text-[var(--color-official-text-muted)]">{children}</div>;
}

export function PaginationControls<T>({
  result,
  onPage,
}: {
  result: PageResult<T>;
  onPage: (page: number) => void;
}) {
  const canPrevious = result.page > 0;
  const canNext = hasNextPage(result);
  const start = result.count === 0 ? 0 : result.page * result.pageSize + 1;
  const end = result.page * result.pageSize + result.rows.length;

  if (!canPrevious && !canNext && (result.count ?? 0) <= result.pageSize) return null;

  return (
    <div className="mt-4 flex flex-col gap-3 border-t border-[var(--color-official-border)] pt-4 text-sm text-[var(--color-official-text-muted)] sm:flex-row sm:items-center sm:justify-between">
      <span>
        Showing {start.toLocaleString()}-{end.toLocaleString()}
        {typeof result.count === 'number' && <> of {result.count.toLocaleString()}</>}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!canPrevious}
          onClick={() => onPage(result.page - 1)}
          className="min-h-11 rounded-full border border-[var(--color-official-border)] px-4 text-sm font-bold transition-colors enabled:cursor-pointer enabled:hover:border-[var(--color-official-link)] disabled:opacity-40"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={!canNext}
          onClick={() => onPage(result.page + 1)}
          className="min-h-11 rounded-full border border-[var(--color-official-border)] px-4 text-sm font-bold transition-colors enabled:cursor-pointer enabled:hover:border-[var(--color-official-link)] disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
