"use client";

import React, { useState, useEffect } from "react";

export default function GlobalAlertProvider({ children }: { children: React.ReactNode }) {
  const [alertState, setAlertState] = useState<{
    message: string;
    isOpen: boolean;
    type: "success" | "error" | "info";
  }>({
    message: "",
    isOpen: false,
    type: "info",
  });

  useEffect(() => {
    const originalAlert = window.alert;

    window.alert = (message: any) => {
      const msgStr = String(message);
      let type: "success" | "error" | "info" = "info";

      const lower = msgStr.toLowerCase();
      if (
        lower.includes("thất bại") ||
        lower.includes("lỗi") ||
        lower.includes("không thể") ||
        lower.includes("cảnh báo") ||
        lower.includes("hết quota") ||
        lower.includes("bắt buộc")
      ) {
        type = "error";
      } else if (
        lower.includes("đã") ||
        lower.includes("thành công") ||
        lower.includes("duyệt") ||
        lower.includes("khớp") ||
        lower.includes("lưu")
      ) {
        type = "success";
      }

      setAlertState({
        message: msgStr,
        isOpen: true,
        type,
      });
    };

    return () => {
      window.alert = originalAlert;
    };
  }, []);

  const closeAlert = () => {
    setAlertState((prev) => ({ ...prev, isOpen: false }));
  };

  return (
    <>
      {children}
      {alertState.isOpen && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
          {/* Glassmorphic Backdrop */}
          <div
            className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity duration-300 ease-out"
            onClick={closeAlert}
          />
          {/* Modal Container */}
          <div className="relative z-10 w-full max-w-sm transform overflow-hidden rounded-2xl bg-white p-6 shadow-2xl transition-all duration-300 ease-out scale-100 border border-slate-100 text-center animate-in fade-in zoom-in-95 duration-200">
            {/* Dynamic Alert Icon */}
            {alertState.type === "success" && (
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-500 shadow-inner ring-4 ring-emerald-100/50">
                <svg
                  className="h-7 w-7"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth="2.5"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              </div>
            )}

            {alertState.type === "error" && (
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-rose-50 text-rose-500 shadow-inner ring-4 ring-rose-100/50">
                <svg
                  className="h-7 w-7"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth="2.5"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
                  />
                </svg>
              </div>
            )}

            {alertState.type === "info" && (
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-blue-50 text-blue-500 shadow-inner ring-4 ring-blue-100/50">
                <svg
                  className="h-7 w-7"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth="2.5"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M11.25 11.25l.041-.02a.75.75 0 111.063.852l-.708 2.836a.75.75 0 001.063.852l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
                  />
                </svg>
              </div>
            )}

            {/* Title */}
            <h3 className="text-lg font-bold text-slate-900 mb-2">
              {alertState.type === "success"
                ? "Thành công"
                : alertState.type === "error"
                  ? "Đã xảy ra lỗi"
                  : "Thông báo"}
            </h3>

            {/* Message */}
            <p className="text-sm text-slate-500 mb-6 leading-relaxed whitespace-pre-line text-center">
              {alertState.message}
            </p>

            {/* Close Button */}
            <div className="flex justify-center">
              <button
                type="button"
                className="w-full px-5 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-sm font-semibold text-white transition duration-200 shadow-md hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2"
                onClick={closeAlert}
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
