"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, Notification } from "@/lib/api";

export default function NotificationsPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [items, setItems] = useState<Notification[]>([]);

  const load = () => api.listNotifications().then(setItems).catch(() => {});

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api.me().then((u) => setEmail(u.email));
    load();
  }, [router]);

  return (
    <div>
      <main className="mx-auto max-w-3xl">
        <Link href="/dashboard" className="text-sm text-accent hover:underline">← Dashboard</Link>
        <div className="mt-4 flex items-center justify-between">
          <h1 className="text-2xl font-bold">Thông báo</h1>
          <button type="button" className="btn-secondary text-xs" onClick={async () => { await api.markAllNotificationsRead(); load(); }}>
            Đánh dấu đã đọc
          </button>
        </div>
        <div className="mt-6 space-y-3">
          {items.map((n) => (
            <div key={n.id} className={`card ${n.is_read ? "opacity-70" : "border-accent/30"}`}>
              <h3 className="font-semibold">{n.title}</h3>
              <p className="mt-1 text-sm text-slate-600">{n.message}</p>
              <p className="mt-2 text-xs text-slate-400">{new Date(n.created_at).toLocaleString("vi-VN")}</p>
              {n.link && (
                <Link href={n.link.replace("http://localhost:3000", "")} className="mt-2 inline-block text-sm text-accent hover:underline">
                  Xem chi tiết →
                </Link>
              )}
            </div>
          ))}
          {items.length === 0 && <div className="card text-slate-500">Chưa có thông báo.</div>}
        </div>
      </main>
    </div>
  );
}
