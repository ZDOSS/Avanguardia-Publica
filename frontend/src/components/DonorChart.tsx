import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from "recharts";

interface DonorChartProps {
  byDonorType: Record<string, number>;
  byCycle: Record<string, number>;
}

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

export function DonorTypeChart({ byDonorType }: { byDonorType: Record<string, number> }) {
  const data = Object.entries(byDonorType).map(([name, value]) => ({
    name: name.replaceAll("_", " ").replace(/\b\w/g, (l) => l.toUpperCase()),
    value,
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={80}
            paddingAngle={5}
            dataKey="value"
          >
            {data.map((_, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value: number) => `$${value.toLocaleString()}`}
          />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CycleTimelineChart({ byCycle }: { byCycle: Record<string, number> }) {
  const data = Object.entries(byCycle)
    .map(([cycle, amount]) => ({
      cycle,
      amount,
    }))
    .sort((a, b) => a.cycle.localeCompare(b.cycle));

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="cycle" />
          <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
          <Tooltip
            formatter={(value: number) => `$${value.toLocaleString()}`}
            labelFormatter={(label) => `Cycle ${label}`}
          />
          <Bar dataKey="amount" fill="#3b82f6" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ContributionBarChart({ byDonorType }: { byDonorType: Record<string, number> }) {
  const data = Object.entries(byDonorType).map(([name, value]) => ({
    name: name.replaceAll("_", " ").replace(/\b\w/g, (l) => l.toUpperCase()),
    value,
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
          <YAxis type="category" dataKey="name" width={100} />
          <Tooltip
            formatter={(value: number) => `$${value.toLocaleString()}`}
          />
          <Bar dataKey="value" fill="#10b981" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function DonorChart({ byDonorType, byCycle }: DonorChartProps) {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div className="border rounded-lg p-4 bg-white">
        <h4 className="text-sm font-semibold text-gray-700 mb-2">By Donor Type</h4>
        <DonorTypeChart byDonorType={byDonorType} />
      </div>
      <div className="border rounded-lg p-4 bg-white">
        <h4 className="text-sm font-semibold text-gray-700 mb-2">By Election Cycle</h4>
        <CycleTimelineChart byCycle={byCycle} />
      </div>
    </div>
  );
}
