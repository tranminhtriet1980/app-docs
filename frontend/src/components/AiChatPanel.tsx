"use client";

import { useState } from "react";
import { api } from "@/lib/api";

const SUGGESTIONS = [
  "Tóm tắt nội dung hồ sơ này",
  "Liệt kê thông tin hộ chiếu đã trích xuất",
  "Còn thiếu thông tin gì quan trọng?",
];

export default function AiChatPanel({ applicantId }: { applicantId: string }) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "ai"; text: string }[]>([]);
  const [busy, setBusy] = useState(false);

  const send = async (q: string) => {
    if (!q.trim() || busy) return;
    setMessages((m) => [...m, { role: "user", text: q }]);
    setQuestion("");
    setBusy(true);
    try {
      const res = await api.aiChat(applicantId, q);
      setMessages((m) => [...m, { role: "ai", text: res.answer }]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "ai", text: e instanceof Error ? e.message : "Lỗi khi gọi AI" },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card mt-8">
      <h2 className="font-semibold">AI Chat với hồ sơ</h2>
      <p className="mt-1 text-xs text-slate-500">
        Hỏi về dữ liệu đã merge và trích xuất từ tài liệu (cần OPENAI_API_KEY).
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            className="rounded-full bg-slate-100 px-3 py-1 text-xs hover:bg-slate-200"
            onClick={() => send(s)}
            disabled={busy}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="mt-4 max-h-64 space-y-3 overflow-y-auto rounded border bg-slate-50 p-3 text-sm">
        {messages.length === 0 && (
          <p className="text-slate-400">Chưa có hội thoại. Chọn gợi ý hoặc nhập câu hỏi.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : ""}>
            <span
              className={`inline-block rounded-lg px-3 py-2 ${
                m.role === "user" ? "bg-accent text-white" : "bg-white border"
              }`}
            >
              {m.text}
            </span>
          </div>
        ))}
      </div>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(question);
        }}
      >
        <input
          className="input flex-1"
          placeholder="VD: Tóm tắt hồ sơ, so sánh passport và visa..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={busy}
        />
        <button type="submit" className="btn-primary shrink-0" disabled={busy}>
          {busy ? "..." : "Gửi"}
        </button>
      </form>
    </div>
  );
}
