"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, DashboardStats, getToken, UserAdmin } from "@/lib/api";

const ROLE_LABELS: Record<string, string> = {
  user: "User",
  staff: "Staff",
  admin: "Admin",
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export default function UsersAdminPage() {
  const router = useRouter();
  const [role, setRole] = useState("");
  const [users, setUsers] = useState<UserAdmin[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState<"user" | "staff" | "admin">("user");
  const [newCanCreate, setNewCanCreate] = useState(true);
  const [newQuota, setNewQuota] = useState(50);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    Promise.all([api.me(), api.listUsers(), api.getAdminStats()])
      .then(([me, list, st]) => {
        if (me.role !== "admin" && me.role !== "staff") {
          router.replace("/dashboard");
          return;
        }
        setRole(me.role);
        if (me.role === "admin") {
          setUsers(list);
        }
        setStats(st);
      })
      .catch(() => router.replace("/dashboard"))
      .finally(() => setLoading(false));
  }, [router]);

  const createUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newEmail.trim() || newPassword.length < 6) {
      alert("Email và mật khẩu (tối thiểu 6 ký tự) là bắt buộc");
      return;
    }
    setCreating(true);
    try {
      const created = await api.createUser({
        email: newEmail.trim(),
        password: newPassword,
        full_name: newName.trim() || undefined,
        role: newRole,
        can_create_applicants: newCanCreate,
        max_applicants_per_month: newQuota,
      });
      setUsers((prev) => [created, ...prev]);
      setNewEmail("");
      setNewPassword("");
      setNewName("");
      setNewRole("user");
      setNewCanCreate(true);
      setNewQuota(50);
      setShowForm(false);
      const st = await api.getAdminStats();
      setStats(st);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Tạo user thất bại");
    } finally {
      setCreating(false);
    }
  };

  const updateUser = async (userId: string, patch: Partial<UserAdmin>) => {
    setSavingId(userId);
    try {
      const updated = await api.updateUser(userId, patch);
      setUsers((prev) => prev.map((u) => (u.id === userId ? updated : u)));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Cập nhật thất bại");
    } finally {
      setSavingId(null);
    }
  };

  const resetPassword = async (u: UserAdmin) => {
    const pwd = window.prompt(`Nhập mật khẩu mới cho ${u.email} (tối thiểu 6 ký tự):`);
    if (pwd === null) return;
    if (pwd.length < 6) {
      alert("Mật khẩu phải có tối thiểu 6 ký tự");
      return;
    }
    setSavingId(u.id);
    try {
      const r = await api.resetUserPassword(u.id, pwd);
      alert(r.message);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Đổi mật khẩu thất bại");
    } finally {
      setSavingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500">
        Đang tải...
      </div>
    );
  }

  return (
    <div>
      <main className="mx-auto max-w-6xl">
        <div className="mb-6 flex items-center gap-4">
          <Link href="/dashboard" className="text-sm text-accent hover:underline">
            ← Quay lại Dashboard
          </Link>
        </div>

        <h1 className="text-2xl font-bold">Quản lý người dùng</h1>
        <p className="mt-1 text-sm text-slate-500">
          Phân quyền tạo hồ sơ · Vai trò · Kích hoạt/vô hiệu tài khoản
        </p>

        {stats && (
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <div className="card">
              <p className="text-sm text-slate-500">Tổng người dùng</p>
              <p className="text-2xl font-bold">{stats.total_users ?? "—"}</p>
            </div>
            <div className="card">
              <p className="text-sm text-slate-500">Tổng hồ sơ (hệ thống)</p>
              <p className="text-2xl font-bold">{stats.total_applicants}</p>
            </div>
            <div className="card">
              <p className="text-sm text-slate-500">Quyền của bạn</p>
              <p className="text-2xl font-bold capitalize">{role}</p>
            </div>
          </div>
        )}

        {role !== "admin" ? (
          <div className="card mt-8 text-slate-600">
            Chỉ <strong>Admin</strong> mới có thể chỉnh quyền người dùng. Staff có thể xem thống kê tổng
            trên Dashboard.
          </div>
        ) : (
          <>
          <div className="card mt-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-semibold">Danh sách người dùng</h2>
              <button
                type="button"
                className="btn-primary"
                onClick={() => setShowForm((v) => !v)}
              >
                {showForm ? "Đóng form" : "+ Tạo user mới"}
              </button>
            </div>
            {showForm && (
              <form onSubmit={createUser} className="mt-6 grid gap-3 border-t pt-6 sm:grid-cols-2">
                <div>
                  <label className="label">Email *</label>
                  <input
                    type="email"
                    className="input"
                    required
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                    placeholder="user@company.com"
                  />
                </div>
                <div>
                  <label className="label">Mật khẩu *</label>
                  <input
                    type="password"
                    className="input"
                    required
                    minLength={6}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Tối thiểu 6 ký tự"
                  />
                </div>
                <div>
                  <label className="label">Họ tên</label>
                  <input
                    className="input"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="Nguyễn Văn A"
                  />
                </div>
                <div>
                  <label className="label">Vai trò</label>
                  <select
                    className="input"
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value as typeof newRole)}
                  >
                    {Object.entries(ROLE_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>{l}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Quota hồ sơ/tháng</label>
                  <input
                    type="number"
                    className="input"
                    min={1}
                    value={newQuota}
                    onChange={(e) => setNewQuota(Number(e.target.value))}
                  />
                </div>
                <div className="flex items-end">
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={newCanCreate}
                      onChange={(e) => setNewCanCreate(e.target.checked)}
                    />
                    Được tạo hồ sơ
                  </label>
                </div>
                <div className="sm:col-span-2">
                  <button type="submit" className="btn-primary" disabled={creating}>
                    {creating ? "Đang tạo..." : "Tạo tài khoản"}
                  </button>
                </div>
              </form>
            )}
          </div>
          <div className="card mt-6 overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="pb-3 pr-4 font-medium">Email</th>
                  <th className="pb-3 pr-4 font-medium">Tên</th>
                  <th className="pb-3 pr-4 font-medium">Vai trò</th>
                  <th className="pb-3 pr-4 font-medium">Tạo hồ sơ</th>
                  <th className="pb-3 pr-4 font-medium">Trạng thái</th>
                  <th className="pb-3 pr-4 font-medium">Quota/tháng</th>
                  <th className="pb-3 pr-4 font-medium">Hồ sơ</th>
                  <th className="pb-3 pr-4 font-medium">Ngày tạo</th>
                  <th className="pb-3 font-medium">Hành động</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-slate-100">
                    <td className="py-3 pr-4">{u.email}</td>
                    <td className="py-3 pr-4">{u.full_name || "—"}</td>
                    <td className="py-3 pr-4">
                      <select
                        className="input py-1"
                        value={u.role}
                        disabled={savingId === u.id}
                        onChange={(e) => updateUser(u.id, { role: e.target.value as UserAdmin["role"] })}
                      >
                        {Object.entries(ROLE_LABELS).map(([v, l]) => (
                          <option key={v} value={v}>
                            {l}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="py-3 pr-4">
                      <label className="inline-flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={u.can_create_applicants}
                          disabled={savingId === u.id}
                          onChange={(e) => updateUser(u.id, { can_create_applicants: e.target.checked })}
                        />
                        <span className="text-xs">{u.can_create_applicants ? "Có" : "Không"}</span>
                      </label>
                    </td>
                    <td className="py-3 pr-4">
                      <label className="inline-flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={u.is_active}
                          disabled={savingId === u.id}
                          onChange={(e) => updateUser(u.id, { is_active: e.target.checked })}
                        />
                        <span className="text-xs">{u.is_active ? "Hoạt động" : "Vô hiệu"}</span>
                      </label>
                    </td>
                    <td className="py-3 pr-4">
                      <input
                        type="number"
                        className="input w-20 py-1"
                        defaultValue={u.max_applicants_per_month ?? 50}
                        disabled={savingId === u.id}
                        onBlur={(e) => updateUser(u.id, { max_applicants_per_month: Number(e.target.value) })}
                      />
                    </td>
                    <td className="py-3 pr-4">{u.applicant_count}</td>
                    <td className="py-3 pr-4">{formatDate(u.created_at)}</td>
                    <td className="py-3">
                      <button
                        type="button"
                        className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:border-brand-500 hover:text-brand-600 disabled:opacity-50"
                        disabled={savingId === u.id}
                        onClick={() => resetPassword(u)}
                      >
                        🔑 Đổi MK
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}

        <div className="card mt-8 bg-slate-50">
          <h2 className="font-semibold">Phân quyền theo vai trò</h2>
          <ul className="mt-3 space-y-2 text-sm text-slate-600">
            <li>
              <strong>User</strong> — Tạo hồ sơ (nếu được bật), quản lý hồ sơ của mình, xóa hồ sơ nháp.
            </li>
            <li>
              <strong>Staff</strong> — Xem thống kê toàn hệ thống, hỗ trợ xử lý hồ sơ (truy cập mọi hồ sơ qua
              link trực tiếp).
            </li>
            <li>
              <strong>Admin</strong> — Quản lý user, phân quyền tạo hồ sơ, xóa mọi hồ sơ (force).
            </li>
          </ul>
        </div>
      </main>
    </div>
  );
}
