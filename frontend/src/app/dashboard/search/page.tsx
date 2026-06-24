"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import StatusBadge from "@/components/StatusBadge";
import { api, SearchResult, getToken } from "@/lib/api";

function SearchContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") || "");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  useEffect(() => {
    const initial = searchParams.get("q");
    if (initial && initial.length >= 2) {
      setQ(initial);
      api.globalSearch(initial).then(setResult).catch(() => setResult(null));
    }
  }, [searchParams]);

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (q.trim().length < 2) return;
    setLoading(true);
    try {
      setResult(await api.globalSearch(q.trim()));
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <main className="mx-auto max-w-6xl">
        <Link href="/dashboard" className="text-sm text-accent hover:underline">← Dashboard</Link>
        <h1 className="mt-4 text-2xl font-bold">Tìm kiếm thông minh</h1>
        <p className="text-sm text-slate-500">
          Tên hồ sơ, khách hàng, dự án, tên file, loại tài liệu, tag và nội dung đã trích xuất.
        </p>
        <form onSubmit={run} className="mt-6 flex gap-2">
          <input
            className="input flex-1"
            placeholder="VD: DANG VAN HUNG, passport, hợp đồng..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Đang tìm..." : "Tìm"}
          </button>
        </form>

        {result && (
          <div className="mt-8 space-y-8">
            <section>
              <h2 className="mb-3 font-semibold">Hồ sơ ({result.applicants.length})</h2>
              {result.applicants.length === 0 && (
                <p className="text-sm text-slate-500">Không có hồ sơ phù hợp.</p>
              )}
              <div className="space-y-2">
                {result.applicants.map((a) => (
                  <Link key={a.id} href={`/applicants/${a.id}/review`} className="card block hover:border-accent">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{a.display_name}</span>
                      <StatusBadge status={a.status} />
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {[a.client_name, a.project_name, a.department].filter(Boolean).join(" · ") || "—"}
                      {a.tags?.length ? ` · #${a.tags.join(" #")}` : ""}
                    </p>
                  </Link>
                ))}
              </div>
            </section>
            <section>
              <h2 className="mb-3 font-semibold">Tài liệu ({result.documents.length})</h2>
              {result.documents.length === 0 && (
                <p className="text-sm text-slate-500">Không có tài liệu phù hợp.</p>
              )}
              <div className="space-y-2">
                {result.documents.map((d) => (
                  <Link
                    key={d.id}
                    href={`/applicants/${d.applicant_id}/upload`}
                    className="card block hover:border-accent text-sm"
                  >
                    <span className="font-medium">{d.filename}</span>
                    <span className="text-slate-500"> — {d.applicant_name}</span>
                    {d.document_type && (
                      <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs">{d.document_type}</span>
                    )}
                  </Link>
                ))}
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={null}>
      <SearchContent />
    </Suspense>
  );
}
