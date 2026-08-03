"use client";
import { useEffect, useMemo, useState } from "react";

import { useCompanies, useEvolution, usePeriods, useTranscript } from "@/lib/private-hooks";

type Period = { fiscal_year: number; fiscal_quarter: number };

export default function CallsTab() {
  const { data: comp } = useCompanies();
  const [ticker, setTicker] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period | null>(null);
  const [lang, setLang] = useState<"en" | "ko">("en");
  const [pickerOpen, setPickerOpen] = useState(false);

  const { data: periodsData } = usePeriods(ticker);
  const periods: Period[] = periodsData?.periods ?? [];

  // auto-select the latest period when a company (or its periods) loads
  useEffect(() => {
    if (periods.length && !periods.find((p) => period && p.fiscal_year === period.fiscal_year && p.fiscal_quarter === period.fiscal_quarter)) {
      setPeriod(periods[0]);
    }
    if (!periods.length) setPeriod(null);
  }, [periodsData]); // eslint-disable-line

  const { data: tr, isLoading: trLoading, error: trError } =
    useTranscript(ticker, period?.fiscal_year ?? null, period?.fiscal_quarter ?? null);
  const { data: evo } = useEvolution(ticker);

  return (
    <div className="flex h-full">
      {/* LEFT: sectors → companies */}
      <aside className="w-60 shrink-0 overflow-y-auto border-r border-slate-200 bg-white">
        {comp?.sectors?.map((s: any) => (
          <div key={s.sector}>
            <div className="sticky top-0 bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">
              {s.sector}
            </div>
            {s.companies.map((c: any) => (
              <button key={c.ticker} onClick={() => { setTicker(c.ticker); setPeriod(null); }}
                className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50 ${ticker === c.ticker ? "bg-blue-50 font-medium text-blue-700" : "text-slate-700"}`}>
                <span>{c.ticker}</span>
                <span className={`text-[10px] ${c.has_transcripts ? "text-emerald-500" : "text-slate-300"}`}>
                  {c.has_transcripts ? `${c.periods.length}개` : "—"}
                </span>
              </button>
            ))}
          </div>
        ))}
        {!comp && <p className="p-3 text-sm text-slate-400">불러오는 중…</p>}
      </aside>

      {/* CENTER: period picker (thin) + full transcript */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="relative border-b border-slate-200 bg-white px-4 py-1.5">
          {!ticker ? (
            <span className="text-sm text-slate-400">왼쪽에서 기업을 선택하세요</span>
          ) : (
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold">{tr?.company ?? ticker}</span>
              <button onClick={() => setPickerOpen((o) => !o)}
                className="rounded-md border border-slate-300 px-2.5 py-0.5 text-sm">
                {period ? `FY${period.fiscal_year} Q${period.fiscal_quarter}` : "연도·분기"} ▾
              </button>
              <div className="ml-auto flex overflow-hidden rounded-md border border-slate-300 text-xs">
                {(["en", "ko"] as const).map((l) => (
                  <button key={l} onClick={() => setLang(l)}
                    className={`px-2.5 py-0.5 ${lang === l ? "bg-slate-900 text-white" : "text-slate-600"}`}>
                    {l === "en" ? "영어 원문" : "한국어"}
                  </button>
                ))}
              </div>
              {pickerOpen && (
                <div className="absolute left-4 top-9 z-10 grid max-h-64 w-72 grid-cols-2 gap-1 overflow-y-auto rounded-md border border-slate-200 bg-white p-2 shadow-lg">
                  {periods.map((p) => (
                    <button key={`${p.fiscal_year}Q${p.fiscal_quarter}`}
                      onClick={() => { setPeriod(p); setPickerOpen(false); }}
                      className={`rounded px-2 py-1 text-sm hover:bg-slate-100 ${period?.fiscal_year === p.fiscal_year && period?.fiscal_quarter === p.fiscal_quarter ? "bg-blue-50 text-blue-700" : ""}`}>
                      FY{p.fiscal_year} Q{p.fiscal_quarter}
                    </button>
                  ))}
                  {!periods.length && <span className="col-span-2 p-2 text-xs text-slate-400">수집된 분기가 없습니다.</span>}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {trLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
          {trError && <p className="text-sm text-slate-400">이 분기의 컨콜 원문이 아직 수집되지 않았습니다.</p>}
          {tr?.paragraphs?.map((p: any, i: number) => {
            const text = lang === "ko" ? (p.text_ko ?? null) : p.text_en;
            return (
              <div key={i} className="mb-4">
                <div className="mb-0.5 text-xs font-medium text-slate-500">
                  {p.speaker_name}{p.speaker_role ? ` · ${p.speaker_role}` : ""}
                  <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-400">
                    {p.section_type === "qa" ? "Q&A" : "발표"}
                  </span>
                </div>
                {text ? (
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">{text}</p>
                ) : (
                  <p className="text-sm italic text-slate-400">
                    한국어 번역은 아직 없습니다 (LLM 연결 시 제공). 영어 원문을 보려면 “영어 원문”을 선택하세요.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* RIGHT: last-year evolution summary */}
      <aside className="w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-4">
        <h2 className="mb-2 text-sm font-semibold">최근 1년 변화 요약</h2>
        {!ticker && <p className="text-xs text-slate-400">기업을 선택하면 톤·강조점 변화를 보여줍니다.</p>}
        {evo && evo.llm_ready === false && (
          <p className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-700">
            현재 mock 분석입니다. 실제 톤·강조점 분석은 LLM(anthropic) 연결 시 제공됩니다.
          </p>
        )}
        {evo?.changes?.map((c: any, i: number) => (
          <div key={i} className="mb-3 rounded-lg border border-slate-200 bg-white p-3 text-xs">
            <div className="mb-1 font-medium text-slate-500">{c.from_period} → {c.to_period}</div>
            {c.tone_changes && <p className="text-slate-700">톤: {c.tone_changes}</p>}
            <Chips label="신규 강조" items={c.newly_emerging_topics} tone="emerald" />
            <Chips label="가속" items={c.accelerating_topics} tone="blue" />
            <Chips label="약화" items={c.weakening_topics} tone="amber" />
            <Chips label="소멸" items={c.disappeared_topics} tone="slate" />
          </div>
        ))}
        {evo?.quarters?.map((q: any) => (
          <div key={`${q.fiscal_year}Q${q.fiscal_quarter}`} className="mb-2 text-xs">
            <div className="font-medium text-slate-500">FY{q.fiscal_year} Q{q.fiscal_quarter}</div>
            {q.executive_summary_ko && <p className="text-slate-600">{q.executive_summary_ko}</p>}
          </div>
        ))}
      </aside>
    </div>
  );
}

function Chips({ label, items, tone }: { label: string; items?: string[]; tone: string }) {
  if (!items || !items.length) return null;
  const c: Record<string, string> = {
    emerald: "bg-emerald-50 text-emerald-700", blue: "bg-blue-50 text-blue-700",
    amber: "bg-amber-50 text-amber-700", slate: "bg-slate-100 text-slate-500",
  };
  return (
    <div className="mt-1">
      <span className="text-slate-400">{label}: </span>
      {items.map((x, i) => <span key={i} className={`mr-1 inline-block rounded px-1.5 py-0.5 ${c[tone]}`}>{x}</span>)}
    </div>
  );
}
