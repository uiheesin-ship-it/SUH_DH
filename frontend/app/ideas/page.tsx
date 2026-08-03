"use client";
import { useEffect, useState } from "react";

import { useInvestmentPoints } from "@/lib/private-hooks";

export default function IdeasTab() {
  const { data, isLoading } = useInvestmentPoints();
  const points: any[] = data?.points ?? [];
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => { if (!sel && points.length) setSel(points[0].theme_id); }, [data]); // eslint-disable-line
  const point = points.find((p) => p.theme_id === sel);

  return (
    <div className="flex h-full">
      {/* LEFT: investment points, newest first-mention on top (spec §5) */}
      <aside className="w-72 shrink-0 overflow-y-auto border-r border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-3 py-2 text-xs text-slate-400">
          투자포인트 (최초 언급 최신순)
        </div>
        {isLoading && <p className="p-3 text-sm text-slate-400">불러오는 중…</p>}
        {points.map((p) => (
          <button key={p.theme_id} onClick={() => setSel(p.theme_id)}
            className={`block w-full border-b border-slate-50 px-3 py-2 text-left text-sm hover:bg-slate-50 ${sel === p.theme_id ? "bg-blue-50" : ""}`}>
            <div className="font-medium text-slate-800">{p.theme_name_ko}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-400">
              <span>{(p.first_mentioned || "").slice(0, 10)}</span>
              <span>· 지지 {p.companies.length}사</span>
              {p.update_count > 1 && <span>· {p.update_count}회 갱신</span>}
            </div>
          </button>
        ))}
        {data && !points.length && (
          <p className="p-3 text-xs text-slate-400">
            아직 투자포인트가 없습니다. 컨콜이 여러 분기·여러 기업 쌓이면 생성됩니다.
          </p>
        )}
      </aside>

      {/* CENTER: detail */}
      <section className="min-w-0 flex-1 overflow-y-auto p-6">
        {!point && <p className="text-sm text-slate-400">왼쪽에서 투자포인트를 선택하세요.</p>}
        {point && (
          <div className="mx-auto max-w-3xl">
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold">{point.theme_name_ko}</h1>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">Experimental</span>
              {point.maturity_label && (
                <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">{point.maturity_label}</span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-slate-400">{point.theme_name_en}</p>
            <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
              <span>최초 언급 {(point.first_mentioned || "").slice(0, 10)}</span>
              <span>· Conviction {point.conviction}</span>
              {point.narrative_confirmation_status && <span>· {point.narrative_confirmation_status}</span>}
            </div>

            <p className="mt-4 text-sm text-slate-700">{point.detail.why_it_is_emerging || "—"}</p>

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <L title="지지 기업" items={point.companies} />
              <L title="직접 수혜 후보" items={point.detail.direct_beneficiaries} />
              <L title="2차 수혜 후보" items={point.detail.secondary_beneficiaries} />
              <L title="피해 가능" items={point.detail.potential_losers} />
              <L title="미확인 가정" items={point.detail.unconfirmed_assumptions} />
              <L title="반대 근거/리스크" items={point.detail.risks} />
              <L title="다음 분기 확인 지표" items={point.detail.next_quarter_checkpoints} />
            </div>

            {point.snapshots?.length > 1 && (
              <div className="mt-5">
                <h3 className="text-sm font-medium text-slate-500">분기별 누적 이력</h3>
                <ul className="mt-1 space-y-1 text-xs text-slate-500">
                  {point.snapshots.map((s: any, i: number) => (
                    <li key={i}>{(s.as_of || "").slice(0, 10)} · 지지 {(s.companies || []).length}사 · Score {s.theme_score ?? "—"}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function L({ title, items }: { title: string; items?: string[] }) {
  const list = items ?? [];
  return (
    <div>
      <p className="text-xs font-medium text-slate-500">{title}</p>
      {list.length ? (
        <ul className="ml-4 list-disc text-sm text-slate-700">{list.map((x, i) => <li key={i}>{x}</li>)}</ul>
      ) : (
        <p className="text-sm text-slate-300">—</p>
      )}
    </div>
  );
}
