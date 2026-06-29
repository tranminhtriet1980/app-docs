import type { ReactNode } from "react";

type Tone = "brand" | "sky" | "amber" | "emerald" | "rose" | "violet";

const TONE: Record<Tone, string> = {
  brand: "bg-brand-50 text-brand-600",
  sky: "bg-sky-50 text-sky-600",
  amber: "bg-amber-50 text-amber-600",
  emerald: "bg-emerald-50 text-emerald-600",
  rose: "bg-rose-50 text-rose-600",
  violet: "bg-violet-50 text-violet-600",
};

export default function KpiCard({
  label,
  value,
  trend,
  trendUp,
  variant = "default",
  tone = "brand",
  icon,
}: {
  label: string;
  value: number | string;
  trend?: string;
  trendUp?: boolean;
  variant?: "default" | "danger";
  tone?: Tone;
  icon?: ReactNode;
}) {
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-lg">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-slate-500">{label}</p>
          <p
            className={`mt-2 text-3xl font-bold tracking-tight ${
              variant === "danger" ? "text-rose-600" : "text-slate-900"
            }`}
          >
            {typeof value === "number" ? value.toLocaleString("vi-VN") : value}
          </p>
        </div>
        {icon && (
          <span
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-xl ${TONE[tone]}`}
          >
            {icon}
          </span>
        )}
      </div>
      {trend && (
        <p
          className={`mt-3 inline-flex items-center gap-1 text-xs font-medium ${
            trendUp === false ? "text-rose-600" : "text-emerald-600"
          }`}
        >
          {trend}
        </p>
      )}
    </div>
  );
}
