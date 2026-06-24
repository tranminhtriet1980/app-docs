"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, User } from "@/lib/api";
import AppSidebar from "./AppSidebar";
import AppHeader from "./AppHeader";

export default function DashboardShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [unread, setUnread] = useState(0);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api
      .me()
      .then((u) => {
        setUser(u);
        return api.unreadCount();
      })
      .then((r) => setUnread(r.count))
      .catch(() => router.replace("/login"))
      .finally(() => setReady(true));
  }, [router, pathname]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-slate-500">
        <div className="flex flex-col items-center gap-3">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-brand-600 border-t-transparent" />
          Đang tải ImmiPath...
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <AppSidebar user={user} />
      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader user={user} unread={unread} />
        <main className="flex-1 overflow-auto p-6 lg:p-8">{children}</main>
      </div>
    </div>
  );
}
