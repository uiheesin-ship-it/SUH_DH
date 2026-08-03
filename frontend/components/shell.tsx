"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/lib/auth";

const TABS = [
  { href: "/", label: "기업별 컨콜" },
  { href: "/ideas", label: "투자포인트" },
  { href: "/search", label: "검색" },
  { href: "/download", label: "컨콜 다운로드" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { token, ready, logout } = useAuth();
  const pathname = usePathname();

  if (!ready) return <div className="p-8 text-slate-400">불러오는 중…</div>;
  if (!token) return <LoginForm />;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-6 border-b border-slate-200 bg-white px-4 py-2">
        <span className="font-semibold text-slate-900">📞 컨콜 리서치</span>
        <nav className="flex gap-1">
          {TABS.map((t) => {
            const active = t.href === "/" ? pathname === "/" : pathname.startsWith(t.href);
            return (
              <Link key={t.href} href={t.href}
                className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                {t.label}
              </Link>
            );
          })}
        </nav>
        <button onClick={logout} className="ml-auto text-xs text-slate-400 hover:text-slate-600">
          로그아웃
        </button>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
    </div>
  );
}

function LoginForm() {
  const { login } = useAuth();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(pw);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-slate-50">
      <form onSubmit={submit} className="w-80 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-1 text-lg font-semibold">컨콜 리서치 (비공개)</h1>
        <p className="mb-4 text-xs text-slate-500">본인 전용입니다. 비밀번호를 입력하세요.</p>
        <input type="password" value={pw} onChange={(e) => setPw(e.target.value)}
          placeholder="비밀번호" autoFocus
          className="mb-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500" />
        {err && <p className="mb-2 text-xs text-red-600">{err}</p>}
        <button disabled={busy}
          className="w-full rounded-md bg-slate-900 py-2 text-sm text-white disabled:opacity-50">
          {busy ? "확인 중…" : "로그인"}
        </button>
      </form>
    </div>
  );
}
