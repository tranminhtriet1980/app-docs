"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, User } from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [current, setCurrent] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [totpUri, setTotpUri] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api.me().then(setUser);
  }, [router]);

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.changePassword(current, newPwd);
      setMsg("Đã đổi mật khẩu");
      setCurrent("");
      setNewPwd("");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Lỗi");
    }
  };

  return (
    <div>
      <main className="mx-auto max-w-lg">
        <Link href="/dashboard" className="text-sm text-accent hover:underline">← Dashboard</Link>
        <h1 className="mt-4 text-2xl font-bold">Cài đặt tài khoản</h1>

        <div className="card mt-6">
          <h2 className="font-semibold">Đổi mật khẩu</h2>
          <form onSubmit={changePassword} className="mt-4 space-y-3">
            <input className="input" type="password" placeholder="Mật khẩu hiện tại" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            <input className="input" type="password" placeholder="Mật khẩu mới" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} required minLength={6} />
            <button type="submit" className="btn-primary">Lưu</button>
          </form>
        </div>

        <div className="card mt-6">
          <h2 className="font-semibold">Xác thực 2 bước (2FA)</h2>
          <p className="mt-1 text-sm text-slate-500">
            {user?.totp_enabled ? "2FA đang bật. Login: mật khẩu|123456" : "Thêm lớp bảo mật với Google Authenticator."}
          </p>
          {!user?.totp_enabled ? (
            <div className="mt-4 space-y-3">
              <button type="button" className="btn-secondary" onClick={async () => {
                const r = await api.setupTotp();
                setTotpUri(r.provisioning_uri);
              }}>
                Tạo mã QR (URI)
              </button>
              {totpUri && (
                <p className="break-all text-xs text-slate-500">Thêm vào app: {totpUri}</p>
              )}
              <input className="input" placeholder="Mã 6 số" value={totpCode} onChange={(e) => setTotpCode(e.target.value)} maxLength={6} />
              <button type="button" className="btn-primary" onClick={async () => {
                await api.enableTotp(totpCode);
                setMsg("2FA đã bật");
                setUser(await api.me());
              }}>
                Bật 2FA
              </button>
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              <input className="input" placeholder="Mã 6 số để tắt" value={totpCode} onChange={(e) => setTotpCode(e.target.value)} />
              <button type="button" className="btn-secondary text-red-600" onClick={async () => {
                await api.disableTotp(totpCode);
                setMsg("2FA đã tắt");
                setUser(await api.me());
              }}>
                Tắt 2FA
              </button>
            </div>
          )}
        </div>

        {msg && <p className="mt-4 text-sm text-green-700">{msg}</p>}
      </main>
    </div>
  );
}
