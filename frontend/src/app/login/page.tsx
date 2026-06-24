"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const emailTrim = email.trim().toLowerCase();
      const pwd = totp.trim() ? `${password}|${totp.trim()}` : password;
      await api.login(emailTrim, pwd);
      router.push("/dashboard");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      setError(
        msg && msg !== "Invalid credentials"
          ? msg
          : "Email hoặc mật khẩu không đúng. Nếu đã bật 2FA, nhập thêm mã 6 số."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 to-blue-50 p-4">
      <div className="card w-full max-w-md">
        <div className="mb-6 flex justify-center">
          <Image src="/images/logo-immi.png" alt="ImmiPath" width={200} height={46} priority />
        </div>
        <h1 className="mb-1 text-xl font-bold text-center">Đăng nhập</h1>
        <p className="mb-6 text-center text-sm text-slate-500">
          Hồ sơ định cư Mỹ · Du học · Du lịch — AI OCR & quản lý tài liệu
        </p>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label">Email</label>
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label className="label">Mật khẩu</label>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <div>
            <label className="label">Mã 2FA (nếu đã bật)</label>
            <input className="input" placeholder="123456" value={totp} onChange={(e) => setTotp(e.target.value)} maxLength={6} />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button type="submit" className="btn-primary w-full" disabled={loading}>
            {loading ? "Đang đăng nhập..." : "Đăng nhập"}
          </button>
        </form>
        <p className="mt-4 text-center text-sm text-slate-500">
          Chưa có tài khoản?{" "}
          <Link href="/register" className="text-accent hover:underline">Đăng ký</Link>
        </p>
      </div>
    </div>
  );
}
