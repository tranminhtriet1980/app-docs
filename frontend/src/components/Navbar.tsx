"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, clearToken } from "@/lib/api";

export default function Navbar({ email, role }: { email?: string; role?: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!email) return;
    api.unreadCount().then((r) => setUnread(r.count)).catch(() => {});
  }, [email, pathname]);

  const logout = () => {
    clearToken();
    router.push("/login");
  };

  const navLink = (href: string, label: string) => (
    <Link
      href={href}
      className={pathname.startsWith(href) ? "font-medium text-accent" : "text-slate-600 hover:text-slate-900"}
    >
      {label}
    </Link>
  );

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <Link href="/dashboard" className="flex items-center gap-3">
          <Image src="/images/logo-immi.png" alt="ImmiPath" width={160} height={37} priority className="h-9 w-auto" />
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          {navLink("/dashboard", "Dashboard")}
          {navLink("/dashboard/search", "Tìm kiếm")}
          {navLink("/dashboard/trash", "Thùng rác")}
          {(role === "admin" || role === "staff") && navLink("/dashboard/reports", "Báo cáo")}
          {(role === "admin" || role === "staff") && navLink("/dashboard/users", "Users")}
          {role === "admin" && navLink("/dashboard/admin", "Admin")}
          {navLink("/dashboard/settings", "Cài đặt")}
          <Link href="/dashboard/notifications" className="relative text-slate-600 hover:text-slate-900">
            🔔
            {unread > 0 && (
              <span className="absolute -right-2 -top-2 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] text-white">
                {unread > 9 ? "9+" : unread}
              </span>
            )}
          </Link>
          {email && (
            <span className="hidden text-slate-500 sm:inline">
              {email}
              {role && role !== "user" && (
                <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs capitalize">{role}</span>
              )}
            </span>
          )}
          <button type="button" onClick={logout} className="btn-secondary text-xs">
            Đăng xuất
          </button>
        </nav>
      </div>
    </header>
  );
}
