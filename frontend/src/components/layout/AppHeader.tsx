"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clearToken, User } from "@/lib/api";

const ROLE_LABELS: Record<string, string> = {
  admin: "Quản trị viên",
  staff: "Nhân viên",
  user: "Người dùng",
};

export default function AppHeader({ user, unread }: { user: User | null; unread: number }) {
  const router = useRouter();
  const [q, setQ] = useState("");

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim().length >= 2) {
      router.push(`/dashboard/search?q=${encodeURIComponent(q.trim())}`);
    }
  };

  const logout = () => {
    clearToken();
    router.push("/login");
  };

  const initials = (user?.full_name || user?.email || "U")
    .split(" ")
    .map((s) => s[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-slate-200 bg-white px-6">
      <form onSubmit={onSearch} className="hidden flex-1 md:block md:max-w-xl">
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">🔍</span>
          <input
            className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2.5 pl-10 pr-4 text-sm focus:border-brand-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            placeholder="Tìm kiếm hồ sơ, mã hồ sơ, người nộp..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </form>

      <div className="ml-auto flex items-center gap-2">
        <Link
          href="/dashboard/notifications"
          className="relative rounded-lg p-2 text-slate-500 hover:bg-slate-100"
          title="Thông báo"
        >
          🔔
          {unread > 0 && (
            <span className="absolute right-1 top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Link>
        <button type="button" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" title="Trợ giúp">
          ❓
        </button>
        <div className="flex items-center gap-3 border-l border-slate-200 pl-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
            {initials}
          </div>
          <div className="hidden sm:block">
            <p className="text-sm font-medium text-slate-900">{user?.full_name || user?.email}</p>
            <p className="text-xs text-slate-500">{ROLE_LABELS[user?.role || "user"]}</p>
          </div>
          <button type="button" onClick={logout} className="text-xs text-slate-500 hover:text-brand-600">
            Thoát
          </button>
        </div>
      </div>
    </header>
  );
}
