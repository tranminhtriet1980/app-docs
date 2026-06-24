export default function KpiCard({
  label,
  value,
  trend,
  trendUp,
  variant = "default",
}: {
  label: string;
  value: number | string;
  trend?: string;
  trendUp?: boolean;
  variant?: "default" | "danger";
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-sm text-slate-500">{label}</p>
      <p className={`mt-2 text-3xl font-bold tracking-tight ${variant === "danger" ? "text-red-600" : "text-slate-900"}`}>
        {typeof value === "number" ? value.toLocaleString("vi-VN") : value}
      </p>
      {trend && (
        <p className={`mt-2 text-xs font-medium ${trendUp === false ? "text-red-600" : "text-emerald-600"}`}>
          {trend}
        </p>
      )}
    </div>
  );
}
