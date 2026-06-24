"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { User } from "@/lib/api";

const CASE_LINKS = [
  { href: "/dashboard?case=immigration", label: "Định cư Mỹ" },
  { href: "/dashboard?case=study_abroad", label: "Du học" },
  { href: "/dashboard?case=tourism", label: "Du lịch" },
];

export default function AppSidebar({ user }: { user: User | null }) {
  const pathname = usePathname();
  const isStaff = user?.role === "staff" || user?.role === "admin";

  const navItem = (href: string, label: string, icon: string, exact = false) => {
    const active = exact ? pathname === href : pathname.startsWith(href);
    return (
      <Link
        href={href}
        className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
          active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        }`}
      >
        <span className="text-lg leading-none">{icon}</span>
        {label}
      </Link>
    );
  };

  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
      <div className="border-b border-slate-100 px-5 py-4">
        <Link href="/dashboard" className="flex items-center gap-2">
          <Image src="/images/logo-immi.png" alt="ImmiPath" width={140} height={32} className="h-8 w-auto" />
        </Link>
        <p className="mt-2 text-[11px] font-medium uppercase tracking-wide text-slate-400">
          Hồ sơ · Định cư · Du học · Du lịch
        </p>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-4">
        {navItem("/dashboard", "Tổng quan", "📊", true)}

        <div className="pt-2">
          <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">Hồ sơ</p>
          {navItem("/dashboard", "Tất cả hồ sơ", "📁")}
          {CASE_LINKS.map((c) => (
            <Link
              key={c.href}
              href={c.href}
              className="ml-6 flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
              {c.label}
            </Link>
          ))}
          {navItem("/dashboard/trash", "Thùng rác", "🗑️")}
        </div>

        {navItem("/dashboard/search", "Tìm kiếm", "🔍")}
        {isStaff && navItem("/dashboard/reports", "Báo cáo & Thống kê", "📈")}
        {user?.role === "admin" && navItem("/dashboard/admin", "Tự động hóa (AI)", "🤖")}
        {isStaff && navItem("/dashboard/users", "Người dùng", "👥")}
        {navItem("/dashboard/settings", "Cài đặt", "⚙️")}
      </nav>

      <div className="m-4 rounded-xl border border-brand-100 bg-gradient-to-br from-brand-50 to-white p-4">
        <p className="text-sm font-semibold text-brand-900">ImmiPath AI Assistant</p>
        <p className="mt-1 text-xs text-slate-600">
          OCR, trích xuất và chat hồ sơ định cư / du học / du lịch Mỹ.
        </p>
        <Link href="/dashboard/search" className="mt-3 inline-block text-xs font-medium text-brand-600 hover:underline">
          Tìm kiếm & hỗ trợ →
        </Link>
      </div>
    </aside>
  );
}
