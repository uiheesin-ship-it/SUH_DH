"use client";
import { useUsage } from "@/lib/hooks";

export default function JobsCostPage() {
  const { data, isLoading } = useUsage();
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">작업 · 비용 모니터링</h1>
      {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Stat title="총 LLM 호출" value={data.total_calls} />
            <Stat title="Input 토큰" value={data.input_tokens} />
            <Stat title="Output 토큰" value={data.output_tokens} />
            <Stat title="예상 비용 (USD)" value={data.estimated_cost} />
            <Stat title="Cache Hit Rate" value={data.cache_hit_rate} />
          </div>
          <div className="card mt-4">
            <h2 className="font-medium">모델별 사용량</h2>
            <table className="mt-2 w-full text-sm">
              <thead className="text-left text-slate-400">
                <tr><th className="py-1">모델</th><th>호출</th><th>Input</th><th>Output</th><th>비용</th></tr>
              </thead>
              <tbody>
                {Object.entries(data.by_model).map(([m, v]: [string, any]) => (
                  <tr key={m} className="border-t border-slate-100">
                    <td className="py-1 font-mono text-xs">{m}</td>
                    <td>{v.calls}</td><td>{v.input_tokens}</td><td>{v.output_tokens}</td>
                    <td>${Number(v.estimated_cost).toFixed(6)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-400">
            평균 처리시간 {data.avg_processing_time}s · 모든 호출은 model_usage 테이블에 기록됩니다
            (토큰·비용·cache_hit·retry_count).
          </p>
        </>
      )}
    </div>
  );
}

function Stat({ title, value }: { title: string; value: number }) {
  return (
    <div className="card">
      <p className="text-xs text-slate-400">{title}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  );
}
