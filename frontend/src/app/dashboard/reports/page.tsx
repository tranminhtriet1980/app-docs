"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import TrendChart from "@/components/TrendChart";
import { api, ExecutiveDashboard, getToken } from "@/lib/api";

export default function ReportsPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("");
  const [data, setData] = useState<ExecutiveDashboard | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api.me().then((u) => {
      if (u.role !== "staff" && u.role !== "admin") {
        router.replace("/dashboard");
        return;
      }
      setEmail(u.email);
      setRole(u.role);
      api.getExecutiveReport().then(setData).catch(() => {});
    });
  }, [router]);

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500">
        Đang tải báo cáo...
      </div>
    );
  }

  return (
    <div>
      <main className="mx-auto max-w-6xl">
        <Link href="/dashboard" className="text-sm text-accent hover:underline">← Dashboard</Link>
        <h1 className="mt-4 text-2xl font-bold">Dashboard điều hành</h1>
        <p className="text-sm text-slate-500">KPI hồ sơ, AI, trùng lặp và hoạt động upload.</p>

        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="card">
            <p className="text-xs text-slate-500">Tổng hồ sơ</p>
            <p className="text-2xl font-bold">{data.total_applicants}</p>
          </div>
          <div className="card">
            <p className="text-xs text-slate-500">Tài liệu hôm nay</p>
            <p className="text-2xl font-bold">{data.documents_today}</p>
          </div>
          <div className="card">
            <p className="text-xs text-slate-500">Hồ sơ thiếu thông tin</p>
            <p className="text-2xl font-bold text-amber-700">{data.profiles_incomplete}</p>
          </div>
          <div className="card">
            <p className="text-xs text-slate-500">Tỷ lệ AI thành công</p>
            <p className="text-2xl font-bold">{data.ai_success_rate}%</p>
          </div>
          <div className="card">
            <p className="text-xs text-slate-500">Tổng tài liệu</p>
            <p className="text-2xl font-bold">{data.total_documents}</p>
          </div>
          <div className="card">
            <p className="text-xs text-slate-500">Trùng lặp phát hiện</p>
            <p className="text-2xl font-bold">{data.duplicate_documents}</p>
          </div>
          <div className="card">
            <p className="text-xs text-slate-500">AI calls (tháng)</p>
            <p className="text-2xl font-bold">{data.ai_calls_this_month}</p>
          </div>
          <div className="card">
            <p className="text-xs text-slate-500">Token AI (tháng)</p>
            <p className="text-2xl font-bold">{data.ai_tokens_this_month.toLocaleString("vi-VN")}</p>
          </div>
        </div>

        {data.upload_trend_weekly.length > 0 && (
          <div className="mt-8">
            <TrendChart data={data.upload_trend_weekly} title="Upload tài liệu theo tuần" />
          </div>
        )}

        {Object.keys(data.by_document_type).length > 0 && (
          <div className="card mt-8">
            <h2 className="mb-3 font-semibold">Hồ sơ theo loại (AI)</h2>
            <table className="w-full text-left text-sm">
              <tbody>
                {Object.entries(data.by_document_type).map(([t, c]) => (
                  <tr key={t} className="border-b border-slate-100">
                    <td className="py-2">{t}</td>
                    <td className="py-2 text-right">{c}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data.top_users.length > 0 && (
          <div className="card mt-8">
            <h2 className="mb-3 font-semibold">Top người dùng (upload)</h2>
            <ul className="space-y-2 text-sm">
              {data.top_users.map((u) => (
                <li key={u.email} className="flex justify-between">
                  <span>{u.email}</span>
                  <span>{u.uploads} file</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </main>
    </div>
  );
}
