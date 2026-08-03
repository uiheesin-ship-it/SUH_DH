import "./globals.css";
import type { Metadata } from "next";

import { AppShell } from "@/components/shell";
import { AuthProvider } from "@/lib/auth";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "컨콜 리서치 (비공개)",
  description: "실적 컨퍼런스콜 전문·검색·투자포인트 (본인 전용)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <Providers>
          <AuthProvider>
            <AppShell>{children}</AppShell>
          </AuthProvider>
        </Providers>
      </body>
    </html>
  );
}
