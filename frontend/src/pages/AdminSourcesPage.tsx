import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchSourceHealth, type SourceHealth } from "../lib/api";

const ADMIN_KEY_STORAGE = "avanguardia:admin_key";

function StatusBadge({ source }: { source: SourceHealth }) {
  let color = "bg-green-100 text-green-800";
  let label = source.status;
  if (source.stale) {
    color = "bg-yellow-100 text-yellow-800";
    label = "stale";
  } else if (source.status === "failed") {
    color = "bg-red-100 text-red-800";
    label = "failed";
  } else if (source.status === "running") {
    color = "bg-blue-100 text-blue-800";
  }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded ${color}`}>{label}</span>
  );
}

export default function AdminSourcesPage() {
  const [adminKey, setAdminKey] = useState(
    () => sessionStorage.getItem(ADMIN_KEY_STORAGE) || ""
  );

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["admin-sources", adminKey],
    queryFn: () => fetchSourceHealth(adminKey || undefined),
    enabled: true,
  });

  const isAuthError = error instanceof Error && /\b401\b/.test(error.message);

  function saveKey(value: string) {
    setAdminKey(value);
    if (value) sessionStorage.setItem(ADMIN_KEY_STORAGE, value);
    else sessionStorage.removeItem(ADMIN_KEY_STORAGE);
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Data Source Health</h2>
      <p className="text-sm text-gray-600 mb-4">
        Admin-only view of ETL ingestion health across all 9 registered sources.
      </p>

      <div className="mb-6 p-3 bg-gray-50 border rounded">
        <label className="block text-xs font-semibold text-gray-600 mb-1">
          Admin API key (X-Admin-Key)
        </label>
        <input
          type="password"
          autoComplete="off"
          className="w-full sm:w-80 border rounded px-2 py-1 text-sm"
          placeholder="Leave blank if ADMIN_API_KEY is unset on the server"
          value={adminKey}
          onChange={(e) => saveKey(e.target.value)}
        />
        <p className="text-xs text-gray-500 mt-1">
          Key is held in sessionStorage only; never sent to non-admin endpoints.
        </p>
      </div>

      {isLoading && <p className="text-gray-500">Loading source health...</p>}
      {error && (
        <p className="text-red-500">
          {isAuthError
            ? "Authentication required. Set the admin key above and retry."
            : (error as Error).message}
        </p>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            <Stat label="Total sources" value={data.summary.total} />
            <Stat label="Healthy" value={data.summary.healthy} accent="green" />
            <Stat label="Stale" value={data.summary.stale} accent="yellow" />
            <Stat label="Failing" value={data.summary.failing} accent="red" />
          </div>

          <div className="overflow-x-auto border rounded bg-white">
            <table className="w-full text-sm">
              <thead className="border-b bg-gray-50">
                <tr className="text-left text-gray-600">
                  <th className="py-2 px-3">Source</th>
                  <th className="py-2 px-3">Status</th>
                  <th className="py-2 px-3">Last Synced</th>
                  <th className="py-2 px-3">Interval</th>
                  <th className="py-2 px-3 text-right">Records</th>
                  <th className="py-2 px-3 text-right">Errors</th>
                </tr>
              </thead>
              <tbody>
                {data.sources.map((s) => (
                  <tr key={s.name} className="border-b last:border-b-0 hover:bg-gray-50">
                    <td className="py-2 px-3 font-mono text-xs">{s.name}</td>
                    <td className="py-2 px-3">
                      <StatusBadge source={s} />
                    </td>
                    <td className="py-2 px-3 text-gray-600">
                      {s.last_synced_at
                        ? new Date(s.last_synced_at).toLocaleString()
                        : "—"}
                    </td>
                    <td className="py-2 px-3 text-gray-600">{s.sync_interval ?? "—"}</td>
                    <td className="py-2 px-3 text-right">{s.total_records.toLocaleString()}</td>
                    <td className="py-2 px-3 text-right">
                      {s.error_count > 0 ? (
                        <span
                          className="text-red-600 cursor-help"
                          title={s.last_error ?? ""}
                        >
                          {s.error_count}
                        </span>
                      ) : (
                        "0"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <button
            className="mt-4 px-3 py-1.5 text-sm border rounded hover:bg-gray-50"
            onClick={() => refetch()}
          >
            Refresh
          </button>
        </>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: "green" | "yellow" | "red";
}) {
  const colors: Record<string, string> = {
    green: "border-green-300 bg-green-50",
    yellow: "border-yellow-300 bg-yellow-50",
    red: "border-red-300 bg-red-50",
  };
  return (
    <div className={`border rounded p-3 ${accent ? colors[accent] : ""}`}>
      <div className="text-xs text-gray-500 uppercase">{label}</div>
      <div className="text-2xl font-bold">{value}</div>
    </div>
  );
}
