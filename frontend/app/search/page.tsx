"use client";
import { useState } from "react";

import { useSearch } from "@/lib/private-hooks";

export default function SearchTab() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const { data, isFetching } = useSearch(query, null);

  return (
    <div className="mx-auto h-full max-w-3xl overflow-y-auto px-4 py-6">
      <form onSubmit={(e) => { e.preventDefault(); setQuery(input); }} className="flex gap-2">
        <input value={input} onChange={(e) => setInput(e.target.value)}
          placeholder="영어 또는 한국어로 컨콜 전체를 검색 (예: HBM supply, 데이터센터)"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500" />
        <button className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white">검색</button>
      </form>

      {isFetching && <p className="mt-4 text-sm text-slate-400">검색 중…</p>}
      {data && (
        <p className="mt-4 text-xs text-slate-400">{data.count}건</p>
      )}
      <div className="mt-2 space-y-3">
        {data?.results?.map((r: any, i: number) => (
          <div key={i} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="mb-1 flex items-center gap-2 text-xs text-slate-400">
              <span className="font-mono font-medium text-slate-600">{r.ticker}</span>
              <span>FY{r.fiscal_year} Q{r.fiscal_quarter}</span>
              <span>· {r.speaker_name}{r.speaker_role ? ` (${r.speaker_role})` : ""}</span>
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px]">{r.section_type === "qa" ? "Q&A" : "발표"}</span>
              <span className="ml-auto text-slate-300">{r.hits} hit</span>
            </div>
            <p className="text-sm text-slate-700">{r.snippet_en}</p>
            {r.snippet_ko && <p className="mt-1 text-sm text-slate-500">{r.snippet_ko}</p>}
          </div>
        ))}
        {data && data.count === 0 && query && (
          <p className="text-sm text-slate-400">결과가 없습니다. (아직 수집되지 않았거나 다른 단어로 시도)</p>
        )}
      </div>
    </div>
  );
}
