import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "실적 컨퍼런스콜 투자 테마",
  description: "미국 실적발표 컨퍼런스콜 기반 투자 테마 발굴 (분석은 영어 원문 기준, 화면은 한국어)",
};

const NAV = [
  { href: "/", label: "마켓 테마" },
  { href: "/companies", label: "기업" },
  { href: "/ideas", label: "투자 아이디어" },
  { href: "/universe", label: "유니버스 커버리지" },
  { href: "/jobs", label: "작업·비용" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <Providers>
          <header className="border-b border-slate-200 bg-white">
            <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
              <span className="font-semibold text-slate-900">📞 컨콜 투자 테마</span>
              <nav className="flex gap-4 text-sm">
                {NAV.map((n) => (
                  <Link key={n.href} href={n.href} className="text-slate-600 hover:text-slate-900">
                    {n.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
          <footer className="mx-auto max-w-6xl px-4 py-8 text-xs text-slate-400">
            모든 점수는 <b>Experimental</b> 지표이며, 통계적으로 검증된 수익률 예측 모델이 아닙니다.
            모든 결론에는 회사·분기·발언자·문단 ID·영어 원문 근거가 연결됩니다.
          </footer>
        </Providers>
      </body>
    </html>
  );
}
