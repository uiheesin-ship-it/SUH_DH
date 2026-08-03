"use client";
import Link from "next/link";

import { ExperimentalTag, MaturityBanner, ScoreBadge } from "@/components/common";
import { useRunBatch, useSeed, useThemes } from "@/lib/hooks";

export default function MarketThemeDashboard() {
  const { data, isLoading, error } = useThemes();
  const seed = useSeed();
  const run = useRunBatch();

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">마켓 테마 대시보드</h1>
        <div className="flex gap-2">
          <button onClick={() => seed.mutate()} className="rounded-md border px-3 py-1.5 text-sm">
            유니버스 시드
          </button>
          <button
            onClick={() => run.mutate()}
            disabled={run.isPending}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {run.isPending ? "분석 실행 중…" : "6개 기업 분석 실행"}
          </button>
        </div>
      </div>

      <MaturityBanner label={data?.maturity} />
      {error && <p className="text-sm text-red-600">백엔드에 연결할 수 없습니다: {String(error)}</p>}
      {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
      {data && data.themes.length === 0 && (
        <p className="text-sm text-slate-500">
          아직 테마가 없습니다. 상단의 “유니버스 시드” → “6개 기업 분석 실행”을 눌러주세요.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data?.themes.map((t) => {
          const p = t.payload ?? {};
          const comps = (p.components ?? {}) as Record<string, number>;
          return (
            <div key={t.theme_id} className="card">
              <div className="flex items-start justify-between">
                <h2 className="font-medium">{t.theme_name_ko}</h2>
                <ExperimentalTag />
              </div>
              <p className="text-xs text-slate-400">{t.theme_name_en}</p>
              <p className="mt-2 text-sm text-slate-600">{p.theme_description_ko as string}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <ScoreBadge label="Theme Score" score={t.theme_score} status={t.score_status} />
                <span className="pill">지지 기업 {String(p.company_count ?? 0)}개</span>
                <span className="pill">Breadth {fmt(comps.breadth)}</span>
                <span className="pill">Numeric {fmt(comps.numeric_confirmation)}</span>
                <span className="pill">ValueChain {fmt(comps.value_chain_confirmation)}</span>
              </div>
              {t.maturity_label && (
                <p className="mt-2 text-xs text-amber-600">{t.maturity_label}</p>
              )}
              <div className="mt-2 text-xs text-slate-400">
                지지: {((p.companies_mentioning as string[]) ?? []).join(", ") || "—"}
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-6 text-xs text-slate-400">
        <Link href="/ideas" className="text-blue-600 hover:underline">투자 아이디어 보드 →</Link>
      </p>
    </div>
  );
}

const fmt = (x?: number) => (x == null ? "—" : x.toFixed(2));
