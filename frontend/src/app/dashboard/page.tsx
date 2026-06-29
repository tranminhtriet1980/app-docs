"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState, Suspense } from "react";
import CaseTypeDonut from "@/components/dashboard/CaseTypeDonut";
import KpiCard from "@/components/dashboard/KpiCard";
import ProcessingLineChart from "@/components/dashboard/ProcessingLineChart";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  Applicant,
  ApplicantAdmin,
  DashboardStats,
  getToken,
  User,
  UserAdmin,
} from "@/lib/api";

const STATUS_OPTIONS = [
  { value: "draft", label: "Nháp" },
  { value: "processing", label: "Đang xử lý" },
  { value: "review", label: "Đang duyệt" },
  { value: "ready_for_export", label: "Sẵn sàng xuất" },
  { value: "exported", label: "Đã xuất" },
] as const;

const CASE_TYPES = [
  { value: "immigration", label: "Định cư Mỹ" },
  { value: "study_abroad", label: "Du học" },
  { value: "tourism", label: "Du lịch" },
  { value: "other", label: "Khác" },
] as const;

const CASE_LABELS: Record<string, string> = {
  immigration: "Định cư",
  study_abroad: "Du học",
  tourism: "Du lịch",
  other: "Khác",
};

function shortId(id: string) {
  return `HS-${id.slice(0, 8).toUpperCase()}`;
}

function DashboardContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const caseFilter = searchParams.get("case") || "";

  const [user, setUser] = useState<User | null>(null);
  const [applicants, setApplicants] = useState<(Applicant | ApplicantAdmin)[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [caseType, setCaseType] = useState<string>("immigration");
  const [isFamilyBundle, setIsFamilyBundle] = useState(true);
  const [principalName, setPrincipalName] = useState("");
  const [spouseName, setSpouseName] = useState("");
  const [childNames, setChildNames] = useState("");
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState("");

  // Bộ lọc danh sách hồ sơ
  const [users, setUsers] = useState<UserAdmin[]>([]);
  const [fSearch, setFSearch] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fCase, setFCase] = useState(caseFilter || "");
  const [fYear, setFYear] = useState("");
  const [fOwner, setFOwner] = useState("");

  const isAdmin = user?.role === "admin";
  const hasFilter = !!(fSearch || fStatus || fCase || fYear || fOwner);

  const loadApplicants = useCallback(
    async (admin: boolean) => {
      const active = !!(fSearch || fStatus || fCase || fYear || (admin && fOwner));
      const base = {
        search: fSearch.trim() || undefined,
        status: fStatus || undefined,
        case_type: fCase || undefined,
        year: fYear ? Number(fYear) : undefined,
      };
      const list = admin
        ? await api.listAdminApplicants({ ...base, owner_id: fOwner || undefined })
        : await api.listApplicants(base);
      setApplicants(active ? list.slice(0, 100) : list.slice(0, 8));
    },
    [fSearch, fStatus, fCase, fYear, fOwner],
  );

  const loadData = useCallback(async () => {
    const me = await api.me();
    const admin = me.role === "admin";
    setUser(me);
    setStats(admin ? await api.getAdminStats() : await api.getStats());
    if (admin) api.listUsers().then(setUsers).catch(() => {});
    await loadApplicants(admin);
  }, [loadApplicants]);

  const resetFilters = async () => {
    setFSearch("");
    setFStatus("");
    setFCase("");
    setFYear("");
    setFOwner("");
    const list = isAdmin ? await api.listAdminApplicants() : await api.listApplicants();
    setApplicants(list.slice(0, 8));
  };

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    loadData()
      .catch(() => router.replace("/login"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const createApplicant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const members: { role: "principal" | "spouse" | "child"; display_name: string }[] = [];
      if (isFamilyBundle) {
        const p = (principalName || name).trim();
        if (p) members.push({ role: "principal", display_name: p });
        const s = spouseName.trim();
        if (s) members.push({ role: "spouse", display_name: s });
        childNames
          .split(/[,;\n]+/)
          .map((c) => c.trim())
          .filter(Boolean)
          .forEach((c) => members.push({ role: "child", display_name: c }));
      }
      await api.createApplicant({
        display_name: name.trim(),
        case_type: caseType as (typeof CASE_TYPES)[number]["value"],
        is_family_bundle: isFamilyBundle,
        members: isFamilyBundle ? members : undefined,
      });
      setName("");
      setPrincipalName("");
      setSpouseName("");
      setChildNames("");
      setShowCreate(false);
      await loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể tạo hồ sơ");
    } finally {
      setCreating(false);
    }
  };

  const deleteApplicant = async (a: Applicant) => {
    const ok = window.confirm(
      `Xóa vĩnh viễn hồ sơ "${a.display_name}"?\n\nToàn bộ dữ liệu trong database và file upload sẽ bị xóa. Không thể hoàn tác.`
    );
    if (!ok) return;
    setDeletingId(a.id);
    try {
      await api.deleteApplicant(a.id, { permanent: true, force: true });
      await loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể xóa hồ sơ");
    } finally {
      setDeletingId("");
    }
  };

  if (loading) return null;

  const canCreate = user?.can_create_applicants !== false;
  const growth = stats?.monthly_growth_pct;
  const growthLabel =
    growth != null ? `${growth >= 0 ? "+" : ""}${growth}% so với tháng trước` : undefined;

  return (
    <>
      <div className="mb-8 overflow-hidden rounded-3xl bg-gradient-to-br from-brand-700 via-brand-600 to-brand-700 p-6 text-white shadow-lg sm:p-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-medium text-white/70">
              Xin chào{user?.full_name ? `, ${user.full_name}` : ""} 👋
            </p>
            <h1 className="mt-1 text-2xl font-bold sm:text-3xl">Tổng quan hồ sơ</h1>
            <p className="mt-1 text-sm text-white/80">
              Quản lý hồ sơ định cư Mỹ, du học &amp; du lịch — AI OCR &amp; xuất form tự động
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {canCreate && (
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-brand-700 shadow-sm transition hover:bg-brand-50"
                onClick={() => setShowCreate(true)}
              >
                <span className="text-lg leading-none">+</span> Tạo hồ sơ mới
              </button>
            )}
            {user?.role !== "user" && (
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-xl bg-white/15 px-4 py-2.5 text-sm font-medium text-white ring-1 ring-white/25 transition hover:bg-white/25"
                onClick={() => api.downloadCsvReport().catch(() => alert("Xuất báo cáo thất bại"))}
              >
                ⬇ Xuất báo cáo
              </button>
            )}
          </div>
        </div>
      </div>

      {showCreate && (
        <div className="mb-6 rounded-2xl border border-brand-200 bg-white p-6 shadow-md ring-1 ring-brand-50">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">➕</span>
            Tạo bộ hồ sơ gia đình
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            <strong>Một bộ hồ sơ</strong> — upload giấy tờ một lần cho cả gia đình, xuất DS-260 riêng cho
            chồng, vợ và từng con.
          </p>
          <form onSubmit={createApplicant} className="mt-4 space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label">Tên bộ hồ sơ / dự án</label>
                <input
                  className="input"
                  placeholder="Gia đình DANG VAN HUNG — EB-3"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="label">Loại hồ sơ</label>
                <select className="input" value={caseType} onChange={(e) => setCaseType(e.target.value)}>
                  {CASE_TYPES.map((c) => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={isFamilyBundle}
                onChange={(e) => setIsFamilyBundle(e.target.checked)}
              />
              Bộ hồ sơ gia đình (chồng + vợ + con)
            </label>
            {isFamilyBundle && (
              <div className="grid gap-3 rounded-lg border border-slate-100 bg-slate-50/80 p-3 sm:grid-cols-2">
                <div>
                  <label className="label">Chủ hồ sơ / Chồng</label>
                  <input
                    className="input"
                    placeholder="DANG VAN HUNG"
                    value={principalName}
                    onChange={(e) => setPrincipalName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="label">Vợ / Chồng (phối ngẫu)</label>
                  <input
                    className="input"
                    placeholder="MAI THI HUONG"
                    value={spouseName}
                    onChange={(e) => setSpouseName(e.target.value)}
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="label">Các con (phân cách bằng dấu phẩy)</label>
                  <input
                    className="input"
                    placeholder="NGUYEN VAN A, NGUYEN THI B"
                    value={childNames}
                    onChange={(e) => setChildNames(e.target.value)}
                  />
                </div>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button type="submit" className="btn-primary" disabled={creating}>
                {creating ? "Đang tạo..." : "Tạo bộ hồ sơ"}
              </button>
              <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>
                Hủy
              </button>
            </div>
          </form>
        </div>
      )}

      {stats && (
        <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard label="Tổng số hồ sơ" value={stats.total_applicants} tone="sky" icon="📁" trend={growthLabel} trendUp={growth == null || growth >= 0} />
          <KpiCard label="Hồ sơ chờ xử lý" value={stats.pending_count ?? 0} tone="amber" icon="⏳" trend={`${stats.open_conflicts} xung đột cần xử lý`} />
          <KpiCard label="Hồ sơ đã hoàn thành" value={stats.completed_count ?? 0} tone="emerald" icon="✅" trend={`${stats.total_exports} lần export`} trendUp />
          <KpiCard label="Hồ sơ quá hạn" value={stats.overdue_count ?? 0} tone="rose" icon="⚠️" variant="danger" trendUp={false} />
        </div>
      )}

      {stats && (
        <div className="mb-8 grid gap-4 sm:grid-cols-3">
          <KpiCard label="Hồ sơ tuần này" value={stats.applicants_this_week ?? 0} tone="brand" icon="🗓️" />
          <KpiCard label="Hồ sơ tháng này" value={stats.applicants_this_month ?? 0} tone="violet" icon="📅" />
          <KpiCard label="Hồ sơ năm nay" value={stats.applicants_this_year ?? 0} tone="sky" icon="📈" />
        </div>
      )}

      {stats?.by_responsible && stats.by_responsible.length > 0 && (
        <div className="mb-8 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center gap-3 border-b border-slate-100 px-6 py-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-lg text-brand-600">
              👥
            </span>
            <div>
              <h2 className="font-semibold text-slate-900">Hồ sơ theo người phụ trách</h2>
              <p className="text-xs text-slate-500">Số bộ hồ sơ đã tạo · tuần này / tháng này / năm nay</p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-left text-sm">
              <thead>
                <tr className="bg-slate-50/80 text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-6 py-3 font-medium">Người phụ trách</th>
                  <th className="px-6 py-3 text-right font-medium">Tuần này</th>
                  <th className="px-6 py-3 text-right font-medium">Tháng này</th>
                  <th className="px-6 py-3 text-right font-medium">Năm nay</th>
                </tr>
              </thead>
              <tbody>
                {stats.by_responsible.map((r) => (
                  <tr key={r.email || r.name} className="border-t border-slate-50 transition hover:bg-slate-50/60">
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-3">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-xs font-semibold text-white">
                          {(r.name || "?").trim().charAt(0).toUpperCase()}
                        </span>
                        <div className="min-w-0">
                          <p className="font-medium text-slate-800">{r.name}</p>
                          {r.email ? <p className="truncate text-xs text-slate-400">{r.email}</p> : null}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-3 text-right font-semibold tabular-nums text-slate-700">{r.week}</td>
                    <td className="px-6 py-3 text-right font-semibold tabular-nums text-slate-700">{r.month}</td>
                    <td className="px-6 py-3 text-right font-semibold tabular-nums text-slate-700">{r.year}</td>
                  </tr>
                ))}
                <tr className="border-t border-slate-100 bg-slate-50 font-semibold text-slate-900">
                  <td className="px-6 py-3">Tổng cộng</td>
                  <td className="px-6 py-3 text-right tabular-nums">{stats.applicants_this_week ?? 0}</td>
                  <td className="px-6 py-3 text-right tabular-nums">{stats.applicants_this_month ?? 0}</td>
                  <td className="px-6 py-3 text-right tabular-nums">{stats.applicants_this_year ?? 0}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="mb-8 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          {stats?.processing_trend && stats.processing_trend.length > 0 && (
            <ProcessingLineChart data={stats.processing_trend as { day: string; completed: number; processing: number; overdue: number }[]} />
          )}
        </div>
        <div>
          {stats && (
            <CaseTypeDonut data={stats.by_case_type || {}} total={stats.total_applicants} />
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-lg text-brand-600">
              🗂️
            </span>
            <h2 className="font-semibold text-slate-900">
              {hasFilter ? `Hồ sơ đã lọc (${applicants.length})` : "Hồ sơ mới cập nhật"}
            </h2>
          </div>
          <Link href="/dashboard/search" className="text-sm font-medium text-brand-600 hover:underline">
            Xem tất cả →
          </Link>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            loadApplicants(!!isAdmin);
          }}
          className="grid gap-3 border-b border-slate-100 bg-slate-50/60 px-6 py-4 sm:grid-cols-2 lg:grid-cols-6"
        >
          <input
            className="input lg:col-span-2"
            placeholder="Tên hồ sơ…"
            value={fSearch}
            onChange={(e) => setFSearch(e.target.value)}
          />
          <select className="input" value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
            <option value="">Mọi trạng thái</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
          <select className="input" value={fCase} onChange={(e) => setFCase(e.target.value)}>
            <option value="">Mọi loại</option>
            {CASE_TYPES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
          <select className="input" value={fYear} onChange={(e) => setFYear(e.target.value)}>
            <option value="">Mọi năm</option>
            {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - i).map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          {isAdmin && (
            <select className="input" value={fOwner} onChange={(e) => setFOwner(e.target.value)}>
              <option value="">Mọi người phụ trách</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>{u.full_name || u.email}</option>
              ))}
            </select>
          )}
          <div className="flex gap-2 sm:col-span-2 lg:col-span-6">
            <button type="submit" className="btn-primary">Lọc</button>
            <button type="button" className="btn-secondary" onClick={resetFilters} disabled={!hasFilter}>
              Đặt lại
            </button>
          </div>
        </form>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/80 text-xs uppercase tracking-wide text-slate-500">
                <th className="px-6 py-3 font-medium">Mã hồ sơ</th>
                <th className="px-6 py-3 font-medium">Tên hồ sơ</th>
                <th className="px-6 py-3 font-medium">Loại</th>
                <th className="px-6 py-3 font-medium">Trạng thái</th>
                <th className="px-6 py-3 font-medium">Tài liệu</th>
                <th className="px-6 py-3 font-medium">Cập nhật</th>
                <th className="px-6 py-3 font-medium text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {applicants.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-slate-500">
                    Chưa có hồ sơ. Bấm &quot;Tạo hồ sơ mới&quot; để bắt đầu.
                  </td>
                </tr>
              )}
              {applicants.map((a) => {
                const isOverdue =
                  stats &&
                  (a.status === "processing" || a.status === "review") &&
                  new Date(a.updated_at).getTime() < Date.now() - 14 * 86400000;
                return (
                  <tr key={a.id} className="border-t border-slate-50 transition hover:bg-brand-50/40">
                    <td className="px-6 py-4 font-mono text-xs text-slate-500">{shortId(a.id)}</td>
                    <td className="px-6 py-4">
                      <Link href={`/applicants/${a.id}/review`} className="flex items-center gap-3 group">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-semibold text-white">
                          {(a.display_name || "?").trim().charAt(0).toUpperCase()}
                        </span>
                        <span className="font-medium text-slate-900 group-hover:text-brand-700">{a.display_name}</span>
                      </Link>
                    </td>
                    <td className="px-6 py-4 text-slate-600">
                      {CASE_LABELS[(a as Applicant).case_type || "immigration"] || "—"}
                    </td>
                    <td className="px-6 py-4">
                      {isOverdue ? <StatusBadge status="overdue" /> : <StatusBadge status={a.status} />}
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                        📄 {a.document_count}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-500">
                      {new Date(a.updated_at).toLocaleString("vi-VN", {
                        day: "2-digit",
                        month: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="inline-flex items-center gap-1">
                        <Link
                          href={`/applicants/${a.id}/review`}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-brand-50 hover:text-brand-600"
                          title="Xem hồ sơ"
                        >
                          👁
                        </Link>
                        <button
                          type="button"
                          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-red-50 hover:text-red-700"
                          title="Xóa hồ sơ"
                          disabled={deletingId === a.id}
                          onClick={() => deleteApplicant(a)}
                        >
                          {deletingId === a.id ? "…" : "🗑"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={null}>
      <DashboardContent />
    </Suspense>
  );
}
