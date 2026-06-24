"use client";

const LABELS: Record<string, string> = {
  immigration: "Định cư Mỹ",
  study_abroad: "Du học",
  tourism: "Du lịch",
  other: "Khác",
};

const COLORS: Record<string, string> = {
  immigration: "#2563eb",
  study_abroad: "#8b5cf6",
  tourism: "#10b981",
  other: "#94a3b8",
};

export default function CaseTypeDonut({
  data,
  total,
}: {
  data: Record<string, number>;
  total: number;
}) {
  const entries = Object.entries(data).filter(([, v]) => v > 0);
  if (!entries.length) {
    entries.push(["immigration", total || 0]);
  }
  const sum = entries.reduce((a, [, v]) => a + v, 0) || 1;
  let offset = 0;
  const segments = entries.map(([key, val]) => {
    const pct = val / sum;
    const seg = { key, val, pct, offset };
    offset += pct;
    return seg;
  });

  const gradient = segments
    .map((s) => {
      const start = s.offset * 360;
      const end = (s.offset + s.pct) * 360;
      return `${COLORS[s.key] || "#94a3b8"} ${start}deg ${end}deg`;
    })
    .join(", ");

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="mb-4 font-semibold text-slate-900">Phân loại hồ sơ</h2>
      <div className="flex flex-col items-center gap-6 sm:flex-row">
        <div
          className="relative h-40 w-40 shrink-0 rounded-full"
          style={{ background: `conic-gradient(${gradient})` }}
        >
          <div className="absolute inset-4 flex flex-col items-center justify-center rounded-full bg-white text-center">
            <span className="text-2xl font-bold text-slate-900">{total.toLocaleString("vi-VN")}</span>
            <span className="text-xs text-slate-500">Tổng hồ sơ</span>
          </div>
        </div>
        <ul className="flex-1 space-y-2 text-sm">
          {segments.map((s) => (
            <li key={s.key} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <span
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: COLORS[s.key] || "#94a3b8" }}
                />
                {LABELS[s.key] || s.key}
              </span>
              <span className="font-medium text-slate-700">
                {Math.round(s.pct * 100)}% ({s.val})
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
