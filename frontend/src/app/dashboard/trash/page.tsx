"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import StatusBadge from "@/components/StatusBadge";
import { api, Applicant, getToken } from "@/lib/api";

export default function TrashPage() {
  const router = useRouter();
  const [items, setItems] = useState<Applicant[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    api.listTrash().then(setItems).catch(() => {});
  };

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api.me().then(() => {
      load();
    }).finally(() => setLoading(false));
  }, [router]);

  const restore = async (id: string) => {
    await api.restoreApplicant(id);
    load();
  };

  const purge = async (a: Applicant) => {
    if (!confirm(`Xóa vĩnh viễn "${a.display_name}"? Không thể hoàn tác.`)) return;
    try {
      await api.deleteApplicant(a.id, { permanent: true });
      load();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Xóa thất bại");
    }
  };

  if (loading) return <div className="flex min-h-screen items-center justify-center">Đang tải...</div>;

  return (
    <div>
      <main className="mx-auto max-w-6xl">
        <Link href="/dashboard" className="text-sm text-accent hover:underline">← Dashboard</Link>
        <h1 className="mt-4 text-2xl font-bold">Thùng rác</h1>
        <p className="text-sm text-slate-500">
          Hồ sơ đã xóa tạm được giữ 30 ngày trước khi admin xóa vĩnh viễn. Chủ hồ sơ có thể khôi phục hoặc xóa
          hẳn khỏi database tại đây.
        </p>
        <div className="mt-6 space-y-3">
          {items.length === 0 && <div className="card text-slate-500">Thùng rác trống.</div>}
          {items.map((a) => (
            <div key={a.id} className="card flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{a.display_name}</span>
                  <StatusBadge status={a.status} />
                </div>
                <p className="text-sm text-slate-500">Xóa lúc: {a.deleted_at ? new Date(a.deleted_at).toLocaleString("vi-VN") : "—"}</p>
              </div>
              <div className="flex gap-2">
                <button type="button" className="btn-primary" onClick={() => restore(a.id)}>Khôi phục</button>
                <button type="button" className="btn-secondary text-red-600" onClick={() => purge(a)}>
                  Xóa vĩnh viễn
                </button>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
