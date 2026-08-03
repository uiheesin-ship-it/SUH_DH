"use client";
import { useMemo, useState } from "react";

import { useAuth } from "@/lib/auth";
import { downloadBundle, useCompanies } from "@/lib/private-hooks";
import { usePeriods } from "@/lib/private-hooks";

// Distinct periods across the whole universe, so the user can pick a time range
// once and apply to all selected companies.
function useAllPeriods() {
  const { data } = useCompanies();
  return useMemo(() => {
    const set = new Set<string>();
    for (const s of data?.sectors ?? []) {
      for (const c of s.companies) {
        for (const [fy, fq] of c.periods ?? []) set.add(`${fy}Q${fq}`);
      }
    }
    return Array.from(set).sort().reverse();
  }, [data]);
}

export default function DownloadTab() {
  const { token } = useAuth();
  const { data } = useCompanies();
  const allPeriods = useAllPeriods();
  const [tickers, setTickers] = useState<string[]>([]);
  const [periods, setPeriods] = useState<string[]>([]);
  const [format, setFormat] = useState<"txt" | "docx">("txt");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toggle = (arr: string[], v: string, set: (x: string[]) => void) =>
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  async function run() {
    setErr(null);
    setBusy(true);
    try {
      await downloadBundle(token, tickers, periods, format);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto h-full max-w-4xl overflow-y-auto px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold">컨콜 다운로드</h1>
      <p className="mb-4 text-xs text-slate-500">기업과 기간을 선택하면 <b>하나의 파일</b>로 묶어 받습니다.</p>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">기업 ({tickers.length})</span>
            <button className="text-xs text-blue-600"
              onClick={() => setTickers(tickers.length ? [] : allTickers(data))}>
              {tickers.length ? "전체 해제" : "전체 선택"}
            </button>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {data?.sectors?.map((s: any) => (
              <div key={s.sector}>
                <div className="bg-slate-50 px-1 py-0.5 text-[11px] text-slate-400">{s.sector}</div>
                {s.companies.filter((c: any) => c.has_transcripts).map((c: any) => (
                  <label key={c.ticker} className="flex items-center gap-2 px-1 py-1 text-sm">
                    <input type="checkbox" checked={tickers.includes(c.ticker)}
                      onChange={() => toggle(tickers, c.ticker, setTickers)} />
                    <span>{c.ticker}</span>
                    <span className="text-[10px] text-slate-400">{c.periods.length}개</span>
                  </label>
                ))}
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">기간 ({periods.length})</span>
            <button className="text-xs text-blue-600"
              onClick={() => setPeriods(periods.length ? [] : allPeriods)}>
              {periods.length ? "전체 해제" : "전체 선택"}
            </button>
          </div>
          <div className="flex max-h-72 flex-wrap gap-1.5 overflow-y-auto">
            {allPeriods.map((p) => (
              <button key={p} onClick={() => toggle(periods, p, setPeriods)}
                className={`rounded-md border px-2 py-1 text-xs ${periods.includes(p) ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 text-slate-600"}`}>
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <div className="flex overflow-hidden rounded-md border border-slate-300 text-xs">
          {(["txt", "docx"] as const).map((f) => (
            <button key={f} onClick={() => setFormat(f)}
              className={`px-3 py-1.5 ${format === f ? "bg-slate-900 text-white" : "text-slate-600"}`}>
              {f.toUpperCase()}
            </button>
          ))}
        </div>
        <button onClick={run} disabled={busy || !tickers.length || !periods.length}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-40">
          {busy ? "만드는 중…" : `다운로드 (${tickers.length}사 × ${periods.length}기간)`}
        </button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
      <p className="mt-2 text-[11px] text-slate-400">
        선택한 기업·기간 중 아직 수집되지 않은 조합은 파일에 “수집 안 됨”으로 표시됩니다(빠지지 않음).
      </p>
    </div>
  );
}

function allTickers(data: any): string[] {
  const out: string[] = [];
  for (const s of data?.sectors ?? []) for (const c of s.companies) if (c.has_transcripts) out.push(c.ticker);
  return out;
}
