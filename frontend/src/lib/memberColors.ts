export type MemberColorStyle = {
  badge: string;
  cardBorder: string;
  cardBg: string;
  rowBorder: string;
};

const PALETTE: MemberColorStyle[] = [
  {
    badge: "bg-blue-600",
    cardBorder: "border-blue-300",
    cardBg: "bg-blue-50/80",
    rowBorder: "border-l-blue-500",
  },
  {
    badge: "bg-violet-600",
    cardBorder: "border-violet-300",
    cardBg: "bg-violet-50/80",
    rowBorder: "border-l-violet-500",
  },
  {
    badge: "bg-emerald-600",
    cardBorder: "border-emerald-300",
    cardBg: "bg-emerald-50/80",
    rowBorder: "border-l-emerald-500",
  },
  {
    badge: "bg-amber-600",
    cardBorder: "border-amber-300",
    cardBg: "bg-amber-50/80",
    rowBorder: "border-l-amber-500",
  },
  {
    badge: "bg-rose-600",
    cardBorder: "border-rose-300",
    cardBg: "bg-rose-50/80",
    rowBorder: "border-l-rose-500",
  },
  {
    badge: "bg-cyan-600",
    cardBorder: "border-cyan-300",
    cardBg: "bg-cyan-50/80",
    rowBorder: "border-l-cyan-500",
  },
];

const FALLBACK: MemberColorStyle = {
  badge: "bg-slate-700",
  cardBorder: "border-slate-300",
  cardBg: "bg-slate-50",
  rowBorder: "border-l-slate-400",
};

export function memberColorByNumber(memberNumber: string | null | undefined): MemberColorStyle {
  const n = parseInt((memberNumber || "").slice(0, 2), 10);
  if (!Number.isFinite(n) || n < 1) return FALLBACK;
  return PALETTE[(n - 1) % PALETTE.length];
}
