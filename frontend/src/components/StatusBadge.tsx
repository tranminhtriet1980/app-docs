const STATUS_STYLES: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  processing: "bg-amber-100 text-amber-800",
  review: "bg-sky-100 text-sky-800",
  ready_for_export: "bg-emerald-100 text-emerald-800",
  exported: "bg-emerald-100 text-emerald-800",
  uploaded: "bg-slate-100 text-slate-600",
  extracted: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  overdue: "bg-red-100 text-red-800",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Nháp",
  processing: "Đang xử lý",
  review: "Chờ phê duyệt",
  ready_for_export: "Sẵn sàng nộp",
  exported: "Đã hoàn thành",
  uploaded: "Đã upload",
  extracted: "Đã trích xuất",
  failed: "Lỗi",
  overdue: "Quá hạn",
};

export default function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] || "bg-slate-100 text-slate-600";
  const label = STATUS_LABELS[status] || status.replace(/_/g, " ");
  return <span className={`badge ${style}`}>{label}</span>;
}
