import type { Metadata } from "next";
import "./globals.css";
import GlobalAlertProvider from "@/components/GlobalAlertProvider";

export const metadata: Metadata = {
  title: "ImmiPath — Quản lý hồ sơ định cư & du học Mỹ",
  description: "Hệ thống AI quản lý hồ sơ định cư Mỹ, du học và du lịch",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <GlobalAlertProvider>{children}</GlobalAlertProvider>
      </body>
    </html>
  );
}
