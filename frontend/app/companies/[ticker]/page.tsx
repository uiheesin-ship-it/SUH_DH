"use client";
import { use } from "react";

import { ConfirmationStatus, ExperimentalTag, ScoreBadge } from "@/components/common";
import { useCompany } from "@/lib/hooks";

export default function CompanyPage({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = use(params);
  const { data, isLoading, error } = useCompany(ticker);

  if (isLoading) return <p className="text-sm text-slate-400">불러오는 중…</p>;
  if (error || !data) return <p className="text-sm text-red-600">불러오지 못했습니다.</p>;

  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <h1 className="text-xl font-semibold">{data.name}</h1>
        <span className="pill">{data.ticker}</span>
        <span className="pill">{data.universe_type}</span>
      </div>
      <p className="mb-4 text-xs text-slate-400">
        {data.sector} · Signal Roles: {data.signal_roles.join(", ")}
      </p>

      {data.calls.map((call) => {
        const s = call.scores;
        const summary = call.summary as Record<string, any>;
        return (
          <div key={`${call.fiscal_year}Q${call.fiscal_quarter}`} className="card mb-4">
            <div className="flex items-center justify-between">
              <h2 className="font-medium">
                FY{call.fiscal_year} Q{call.fiscal_quarter}
              </h2>
              <ExperimentalTag />
            </div>
            <p className="mt-2 text-sm text-slate-700">{summary.executive_summary_ko}</p>

            {s && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <ScoreBadge
                  label="Narrative Momentum"
                  score={s.narrative_momentum?.score}
                  status={s.narrative_momentum?.status}
                />
                <ScoreBadge
                  label="Fundamental Confirmation"
                  score={s.fundamental_confirmation?.score}
                  status={s.fundamental_confirmation?.status}
                />
                <ConfirmationStatus status={s.narrative_confirmation_status} />
                <span className="pill">검증 KPI {s.verified_kpi_count ?? 0}개</span>
                <span className="pill">score_version {s.score_version}</span>
              </div>
            )}

            <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
              <Signals title="Prepared vs Q&A" items={[summary.prepared_vs_qa_gap]} />
              <Signals title="내러티브 vs 숫자" items={[summary.narrative_vs_numbers_gap]} />
              <Signals title="수요 신호" items={summary.demand_signals} />
              <Signals title="가이던스 신호" items={summary.guidance_signals} />
              <Signals title="리스크" items={summary.risks} />
              <Signals title="애널리스트 우려" items={summary.analyst_concerns} />
            </div>
          </div>
        );
      })}

      {data.quarterly_comparisons.length > 0 && (
        <div className="card">
          <h2 className="font-medium">분기 비교 (QoQ)</h2>
          {data.quarterly_comparisons.map((q: any, i) => (
            <div key={i} className="mt-2 text-xs text-slate-600">
              <p className="text-slate-400">{q.from_period} → {q.to_period}</p>
              <Signals title="신규 부상" items={q.payload?.newly_emerging_topics} />
              <Signals title="가속" items={q.payload?.accelerating_topics} />
              <Signals title="약화" items={q.payload?.weakening_topics} />
              <Signals title="소멸" items={q.payload?.disappeared_topics} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Signals({ title, items }: { title: string; items?: (string | null)[] }) {
  const list = (items ?? []).filter(Boolean) as string[];
  if (list.length === 0) return null;
  return (
    <div>
      <p className="font-medium text-slate-500">{title}</p>
      <ul className="ml-4 list-disc text-slate-600">
        {list.map((x, i) => <li key={i}>{x}</li>)}
      </ul>
    </div>
  );
}
