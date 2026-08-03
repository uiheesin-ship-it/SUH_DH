"use client";
import { useCoverage } from "@/lib/hooks";

export default function UniverseCoverage() {
  const { data, isLoading } = useCoverage();
  if (isLoading || !data) return <p className="text-sm text-slate-400">불러오는 중…</p>;
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">유니버스 커버리지</h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat title="총 기업 수" value={data.total_companies} />
        <Counts title="섹터별" map={data.by_sector} />
        <Counts title="Signal Role별" map={data.by_signal_role} />
        <Counts title="밸류체인별" map={data.by_value_chain} />
        <Counts title="구분별" map={data.by_universe_type} />
      </div>
      <div className="card mt-4">
        <h2 className="font-medium">확인 기업이 1개뿐인 Topic (커버리지 부족)</h2>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {data.single_company_topics.length
            ? data.single_company_topics.map((t) => <span key={t} className="pill">{t}</span>)
            : <span className="text-sm text-slate-400">없음</span>}
        </div>
        <p className="mt-3 text-xs text-amber-600">{data.maturity}</p>
      </div>
    </div>
  );
}

function Stat({ title, value }: { title: string; value: number }) {
  return (
    <div className="card">
      <p className="text-xs text-slate-400">{title}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function Counts({ title, map }: { title: string; map: Record<string, number> }) {
  return (
    <div className="card">
      <p className="text-xs text-slate-400">{title}</p>
      <ul className="mt-1 space-y-0.5 text-sm">
        {Object.entries(map).map(([k, v]) => (
          <li key={k} className="flex justify-between"><span className="text-slate-600">{k}</span><span>{v}</span></li>
        ))}
      </ul>
    </div>
  );
}
