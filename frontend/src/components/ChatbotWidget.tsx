"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Source = { id: string; name: string; status?: string };
type Msg = {
  role: "user" | "ai";
  text: string;
  sources?: Source[];
  sourceType?: "data" | "openai" | "none";
};

const SUGGESTIONS = [
  "Tìm hồ sơ KHUC THI LE HANG",
  "DS-260 cần những giấy tờ gì?",
  "Hồ sơ nào đang chờ xử lý?",
];

function BotIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="8" width="18" height="11" rx="3" />
      <path d="M12 8V4M9 3h6" />
      <circle cx="8.5" cy="13" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="13" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1 px-1">
      {[0, 150, 300].map((d) => (
        <span
          key={d}
          className="h-2 w-2 animate-bounce rounded-full bg-slate-400"
          style={{ animationDelay: `${d}ms` }}
        />
      ))}
    </span>
  );
}

export default function ChatbotWidget() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, open]);

  // Hiện câu trả lời dần như đang gõ chữ (typewriter), thời lượng ~đều bất kể độ dài.
  const typeOut = (full: string) =>
    new Promise<void>((resolve) => {
      let i = 0;
      const step = Math.max(2, Math.round(full.length / 60));
      const tick = () => {
        i = Math.min(full.length, i + step);
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          if (last && last.role === "ai") copy[copy.length - 1] = { ...last, text: full.slice(0, i) };
          return copy;
        });
        if (i < full.length) setTimeout(tick, 18);
        else resolve();
      };
      tick();
    });

  const send = async (q: string) => {
    if (!q.trim() || busy) return;
    setMessages((m) => [...m, { role: "user", text: q }]);
    setQuestion("");
    setBusy(true);
    try {
      const res = await api.askAssistant(q.trim());
      setMessages((m) => [
        ...m,
        { role: "ai", text: "", sources: res.sources, sourceType: res.source_type },
      ]);
      await typeOut(res.answer);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "ai", text: e instanceof Error ? e.message : "Lỗi khi gọi trợ lý." },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const waiting = busy && messages[messages.length - 1]?.role === "user";

  return (
    <>
      {/* Nút mở — viên thuốc gradient, có chấm trạng thái */}
      {!open && (
        <button
          type="button"
          aria-label="AI Assistant"
          onClick={() => setOpen(true)}
          className="group fixed bottom-5 right-5 z-50 flex items-center gap-2.5 rounded-full bg-gradient-to-br from-brand-600 to-brand-700 px-5 py-3.5 font-medium text-white shadow-xl ring-4 ring-brand-600/15 transition hover:scale-[1.04] hover:shadow-2xl active:scale-95"
        >
          <span className="relative flex h-6 w-6 items-center justify-center">
            <BotIcon className="h-6 w-6" />
            <span className="absolute -right-1.5 -top-1.5 h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-brand-700" />
          </span>
          <span className="text-sm">AI Assistant</span>
        </button>
      )}

      {open && (
        <div className="fixed bottom-5 right-5 z-50 flex h-[560px] w-[min(92vw,392px)] flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl">
          {/* Header gradient */}
          <div className="flex items-center gap-3 bg-gradient-to-r from-brand-600 to-brand-700 px-4 py-3.5 text-white">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/25">
              <BotIcon className="h-6 w-6" />
            </span>
            <div className="min-w-0">
              <p className="font-semibold leading-tight">AI Assistant — ImmiPath</p>
              <p className="flex items-center gap-1.5 text-[11px] text-white/80">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
                Trực tuyến · Tìm hồ sơ &amp; hỏi đáp định cư
              </p>
            </div>
            <button
              type="button"
              aria-label="Đóng"
              onClick={() => setOpen(false)}
              className="ml-auto flex h-8 w-8 items-center justify-center rounded-full text-white/90 transition hover:bg-white/15"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
          </div>

          {/* Khung hội thoại */}
          <div ref={bodyRef} className="flex-1 space-y-4 overflow-y-auto bg-slate-50 p-4 text-sm">
            {messages.length === 0 && (
              <div className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
                <div className="flex items-start gap-2.5">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600">
                    <BotIcon className="h-5 w-5" />
                  </span>
                  <p className="text-slate-600">
                    Xin chào! 👋 Mình có thể <b>tìm hồ sơ</b> trong dữ liệu hoặc trả lời các câu hỏi về <b>định cư</b>.
                  </p>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="rounded-full border border-brand-100 bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 transition hover:bg-brand-100"
                      onClick={() => send(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`flex gap-2 ${m.role === "user" ? "justify-end" : ""}`}>
                {m.role === "ai" && (
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white">
                    <BotIcon className="h-4 w-4" />
                  </span>
                )}
                <div className="max-w-[80%]">
                  <div
                    className={`whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 shadow-sm ${
                      m.role === "user"
                        ? "rounded-tr-sm bg-gradient-to-br from-brand-600 to-brand-700 text-white"
                        : "rounded-tl-sm border border-slate-100 bg-white text-slate-700"
                    }`}
                  >
                    {m.text || (m.role === "ai" ? <TypingDots /> : "")}
                  </div>
                  {m.role === "ai" && m.sources && m.sources.length > 0 && (
                    <div className="mt-2 space-y-1.5">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                        Hồ sơ liên quan
                      </p>
                      {m.sources.map((s) => (
                        <Link
                          key={s.id}
                          href={`/applicants/${s.id}/review`}
                          className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:border-brand-300 hover:bg-brand-50"
                          onClick={() => setOpen(false)}
                        >
                          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-50 text-[10px] text-brand-700">
                            HS
                          </span>
                          <span className="truncate">{s.name}</span>
                          {s.status ? <span className="ml-auto shrink-0 text-slate-400">{s.status}</span> : null}
                        </Link>
                      ))}
                    </div>
                  )}
                  {m.role === "ai" && m.sourceType === "openai" && m.text && (
                    <p className="mt-1 text-[10px] text-slate-400">✨ Kiến thức chung (OpenAI)</p>
                  )}
                </div>
              </div>
            ))}

            {waiting && (
              <div className="flex gap-2">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white">
                  <BotIcon className="h-4 w-4" />
                </span>
                <div className="rounded-2xl rounded-tl-sm border border-slate-100 bg-white px-3 py-2.5 shadow-sm">
                  <TypingDots />
                </div>
              </div>
            )}
          </div>

          {/* Ô nhập */}
          <form
            className="flex items-center gap-2 border-t border-slate-100 bg-white p-3"
            onSubmit={(e) => {
              e.preventDefault();
              send(question);
            }}
          >
            <input
              className="flex-1 rounded-full border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none transition focus:border-brand-400 focus:bg-white focus:ring-2 focus:ring-brand-100"
              placeholder="Nhập câu hỏi…"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={busy}
            />
            <button
              type="submit"
              aria-label="Gửi"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-600 to-brand-700 text-white shadow-md transition hover:shadow-lg disabled:opacity-50"
              disabled={busy || !question.trim()}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
            </button>
          </form>
        </div>
      )}
    </>
  );
}
