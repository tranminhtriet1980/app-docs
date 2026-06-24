"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiUsageLog, ApiUsageStats, AuditLog, BackupInfo, FormTemplateAdmin, getToken } from "@/lib/api";

export default function AdminHubPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("");
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [templates, setTemplates] = useState<FormTemplateAdmin[]>([]);
  const [tab, setTab] = useState<"audit" | "backup" | "templates" | "usage">("audit");
  const [usageStats, setUsageStats] = useState<ApiUsageStats | null>(null);
  const [usageLogs, setUsageLogs] = useState<ApiUsageLog[]>([]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api.me().then((u) => {
      if (u.role !== "admin") {
        router.replace("/dashboard");
        return;
      }
      setEmail(u.email);
      setRole(u.role);
      api.listAuditLogs().then(setLogs).catch(() => {});
      api.listBackups().then(setBackups).catch(() => {});
      api.listAdminTemplates().then(setTemplates).catch(() => {});
    });
  }, [router]);

  useEffect(() => {
    if (tab !== "usage") return;
    api.getApiUsageStats(30).then(setUsageStats).catch(() => {});
    api.listApiUsageLogs(80).then(setUsageLogs).catch(() => {});
  }, [tab]);

  const tabs = [
    { id: "audit" as const, label: "Audit log" },
    { id: "usage" as const, label: "API & Token" },
    { id: "backup" as const, label: "Sao lưu DB" },
    { id: "templates" as const, label: "Form mẫu" },
  ];

  const fmt = (n: number) => n.toLocaleString("vi-VN");

  return (
    <div>
      <main className="mx-auto max-w-6xl">
        <Link href="/dashboard" className="text-sm text-accent hover:underline">← Dashboard</Link>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-2xl font-bold">Trung tâm Admin</h1>
          <button type="button" className="btn-secondary" onClick={() => api.downloadCsvReport()}>
            Tải báo cáo CSV
          </button>
        </div>
        <div className="mt-6 flex gap-2">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? "btn-primary" : "btn-secondary"}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "audit" && (
          <div className="card mt-6 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b text-slate-500">
                  <th className="pb-2">Thời gian</th>
                  <th className="pb-2">User</th>
                  <th className="pb-2">Hành động</th>
                  <th className="pb-2">Entity</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id} className="border-b border-slate-100">
                    <td className="py-2">{new Date(l.created_at).toLocaleString("vi-VN")}</td>
                    <td className="py-2">{l.user_email || "—"}</td>
                    <td className="py-2">{l.action}</td>
                    <td className="py-2">{l.entity_type}:{l.entity_id.slice(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "usage" && !usageStats && (
          <p className="mt-6 text-sm text-slate-500">Đang tải thống kê API…</p>
        )}

        {tab === "usage" && usageStats && (
          <div className="mt-6 space-y-6">
            {usageStats.monthly_token_budget && usageStats.budget_used_percent != null && usageStats.budget_used_percent >= 80 && (
              <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                Đã dùng {usageStats.budget_used_percent}% ngân sách token tháng ({fmt(usageStats.total_tokens)} / {fmt(usageStats.monthly_token_budget)}).
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="card">
                <p className="text-xs text-slate-500">Tổng token (30 ngày)</p>
                <p className="mt-1 text-2xl font-bold">{fmt(usageStats.total_tokens)}</p>
                <p className="mt-1 text-xs text-slate-500">
                  Prompt {fmt(usageStats.prompt_tokens)} · Completion {fmt(usageStats.completion_tokens)}
                </p>
              </div>
              <div className="card">
                <p className="text-xs text-slate-500">Lượt gọi API</p>
                <p className="mt-1 text-2xl font-bold">{fmt(usageStats.total_calls)}</p>
                <p className="mt-1 text-xs text-slate-500">
                  OK {usageStats.successful_calls} · Lỗi {usageStats.failed_calls}
                </p>
              </div>
              <div className="card">
                <p className="text-xs text-slate-500">Token hôm nay</p>
                <p className="mt-1 text-2xl font-bold">{fmt(usageStats.tokens_today)}</p>
                <p className="mt-1 text-xs text-slate-500">Model: {usageStats.current_model}</p>
              </div>
              <div className="card">
                <p className="text-xs text-slate-500">Ước tính chi phí (USD)</p>
                <p className="mt-1 text-2xl font-bold">${usageStats.estimated_cost_usd.toFixed(4)}</p>
                <p className="mt-1 text-xs text-slate-500">Theo giá cấu hình .env</p>
              </div>
            </div>

            {usageStats.by_operation.length > 0 && (
              <div className="card">
                <h2 className="mb-3 font-semibold">Theo loại thao tác</h2>
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b text-slate-500">
                      <th className="pb-2">Thao tác</th>
                      <th className="pb-2">Lượt gọi</th>
                      <th className="pb-2">Token</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usageStats.by_operation.map((row) => (
                      <tr key={row.operation} className="border-b border-slate-100">
                        <td className="py-2 font-mono text-xs">{row.operation}</td>
                        <td className="py-2">{row.calls}</td>
                        <td className="py-2">{fmt(row.total_tokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {usageStats.by_user && usageStats.by_user.length > 0 && (
              <div className="card">
                <h2 className="mb-3 font-semibold">Theo người dùng</h2>
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b text-slate-500">
                      <th className="pb-2">Email</th>
                      <th className="pb-2">Lượt gọi</th>
                      <th className="pb-2">Token</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usageStats.by_user.map((row) => (
                      <tr key={row.user_id || row.email} className="border-b border-slate-100">
                        <td className="py-2">{row.email}</td>
                        <td className="py-2">{row.calls}</td>
                        <td className="py-2">{fmt(row.total_tokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="card overflow-x-auto">
              <h2 className="mb-3 font-semibold">Lịch sử gọi API gần đây</h2>
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead>
                  <tr className="border-b text-slate-500">
                    <th className="pb-2">Thời gian</th>
                    <th className="pb-2">User</th>
                    <th className="pb-2">Thao tác</th>
                    <th className="pb-2">File</th>
                    <th className="pb-2">Token</th>
                    <th className="pb-2">Trạng thái</th>
                  </tr>
                </thead>
                <tbody>
                  {usageLogs.map((log) => (
                    <tr key={log.id} className="border-b border-slate-100">
                      <td className="py-2 whitespace-nowrap">{new Date(log.created_at).toLocaleString("vi-VN")}</td>
                      <td className="py-2">{log.user_email || "—"}</td>
                      <td className="py-2 font-mono text-xs">{log.operation}</td>
                      <td className="py-2 max-w-[160px] truncate" title={log.filename || ""}>{log.filename || "—"}</td>
                      <td className="py-2">
                        {fmt(log.total_tokens)}
                        <span className="block text-xs text-slate-400">
                          {log.prompt_tokens}+{log.completion_tokens}
                        </span>
                      </td>
                      <td className="py-2">
                        {log.success ? (
                          <span className="text-green-700">OK</span>
                        ) : (
                          <span className="text-red-600" title={log.error_message || ""}>Lỗi</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {usageLogs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-6 text-center text-slate-500">
                        Chưa có lượt gọi API. Upload/xử lý tài liệu để ghi nhận token.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {tab === "backup" && (
          <div className="card mt-6">
            <button
              type="button"
              className="btn-primary mb-4"
              onClick={async () => {
                await api.createBackup();
                setBackups(await api.listBackups());
              }}
            >
              Tạo backup mới
            </button>
            <ul className="space-y-2 text-sm">
              {backups.map((b) => (
                <li key={b.filename} className="flex items-center justify-between rounded border p-3">
                  <span>{b.filename} ({Math.round(b.size_bytes / 1024)} KB)</span>
                  <button
                    type="button"
                    className="btn-secondary text-xs"
                    onClick={async () => {
                      if (!confirm(`Khôi phục ${b.filename}? Cần restart backend.`)) return;
                      await api.restoreBackup(b.filename);
                      alert("Đã khôi phục. Restart backend.");
                    }}
                  >
                    Khôi phục
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {tab === "templates" && (
          <div className="card mt-6">
            <p className="mb-4 text-sm text-slate-500">Upload form mẫu tại đây (admin). User chỉ chọn khi export.</p>
            <form
              className="mb-6 flex flex-wrap gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                const fd = new FormData(e.currentTarget);
                const file = (fd.get("file") as File)?.size ? (fd.get("file") as File) : null;
                if (!file) return;
                await api.uploadFormTemplate(String(fd.get("code")), String(fd.get("name")), file);
                setTemplates(await api.listAdminTemplates());
                e.currentTarget.reset();
              }}
            >
              <input name="code" className="input max-w-[140px]" placeholder="Mã form" required />
              <input name="name" className="input max-w-[180px]" placeholder="Tên hiển thị" />
              <input name="file" type="file" accept=".docx" required />
              <button type="submit" className="btn-primary">Upload</button>
            </form>
            <ul className="space-y-2">
              {templates.map((t) => (
                <li key={t.id} className="flex items-center justify-between rounded border p-3 text-sm">
                  <span>{t.name} ({t.code}) {t.is_active ? "" : "— tắt"}</span>
                  <div className="flex gap-2">
                    <button type="button" className="btn-secondary text-xs" onClick={async () => {
                      await api.toggleTemplate(t.id, !t.is_active);
                      setTemplates(await api.listAdminTemplates());
                    }}>
                      {t.is_active ? "Tắt" : "Bật"}
                    </button>
                    <button type="button" className="btn-secondary text-xs text-red-600" onClick={async () => {
                      if (!confirm("Xóa template?")) return;
                      await api.deleteTemplate(t.id);
                      setTemplates(await api.listAdminTemplates());
                    }}>
                      Xóa
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </main>
    </div>
  );
}
