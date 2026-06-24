"use client";

type Point = { week: string; count: number };

export default function TrendChart({ data, title = "Xu hướng hồ sơ (6 tuần)" }: { data: Point[]; title?: string }) {
  if (!data?.length) return null;
  const max = Math.max(...data.map((d) => d.count), 1);

  return (
    <div className="card">
      <h2 className="mb-4 font-semibold">{title}</h2>
      <div className="flex h-40 items-end gap-3">
        {data.map((d) => (
          <div key={d.week} className="flex flex-1 flex-col items-center gap-1">
            <span className="text-xs font-medium text-slate-600">{d.count}</span>
            <div
              className="w-full rounded-t bg-accent/80 transition-all"
              style={{ height: `${Math.max(8, (d.count / max) * 120)}px` }}
            />
            <span className="text-[10px] text-slate-400">{d.week}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
