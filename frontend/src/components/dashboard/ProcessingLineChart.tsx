"use client";

type Point = { day: string; completed: number; processing: number; overdue: number };

export default function ProcessingLineChart({ data }: { data: Point[] }) {
  if (!data?.length) return null;
  const max = Math.max(...data.flatMap((d) => [d.completed, d.processing, d.overdue]), 1);
  const h = 160;
  const w = 100 / (data.length - 1 || 1);

  const line = (key: keyof Point, color: string) => {
    const points = data
      .map((d, i) => {
        const val = d[key] as number;
        const x = i * w;
        const y = h - (val / max) * (h - 20);
        return `${x},${y}`;
      })
      .join(" ");
    return (
      <polyline fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" points={points} />
    );
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-semibold text-slate-900">Tình hình xử lý hồ sơ</h2>
        <span className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-500">7 ngày qua</span>
      </div>
      <div className="mb-4 flex flex-wrap gap-4 text-xs">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded bg-brand-600" /> Hoàn thành
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded bg-amber-500" /> Đang xử lý
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded bg-red-500" /> Quá hạn
        </span>
      </div>
      <svg viewBox={`0 0 100 ${h}`} className="h-44 w-full" preserveAspectRatio="none">
        {line("completed", "#2563eb")}
        {line("processing", "#f59e0b")}
        {line("overdue", "#ef4444")}
      </svg>
      <div className="mt-2 flex justify-between text-[10px] text-slate-400">
        {data.map((d) => (
          <span key={d.day}>{d.day}</span>
        ))}
      </div>
    </div>
  );
}
