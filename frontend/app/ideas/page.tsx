"use client";
import { ConfirmationStatus, ConvictionBadge, ExperimentalTag, MaturityBanner } from "@/components/common";
import { useInvestmentThemes } from "@/lib/hooks";

export default function IdeasBoard() {
  const { data, isLoading } = useInvestmentThemes();
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">투자 아이디어 보드</h1>
      <MaturityBanner label={data?.maturity} />
      {isLoading && <p className="text-sm text-slate-400">불러오는 중…</p>}
      <div className="space-y-4">
        {data?.investment_themes.map((it, i) => {
          const p = (it.payload ?? {}) as Record<string, any>;
          return (
            <div key={i} className="card">
              <div className="flex items-start justify-between">
                <h2 className="font-medium">{it.investment_theme}</h2>
                <div className="flex gap-1.5">
                  <ConvictionBadge v={it.conviction} />
                  <ExperimentalTag />
                </div>
              </div>
              <p className="mt-1 text-sm text-slate-600">{p.why_it_is_emerging}</p>
              <div className="mt-2">
                <ConfirmationStatus status={it.narrative_confirmation_status} />
                {it.maturity_label && <span className="ml-2 text-xs text-amber-600">{it.maturity_label}</span>}
              </div>
              <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
                <L title="지지 기업" items={p.companies_supporting} />
                <L title="지지 산업" items={p.sectors_supporting} />
                <L title="직접 수혜 후보" items={p.direct_beneficiaries} />
                <L title="2차 수혜 후보" items={p.secondary_beneficiaries} />
                <L title="피해 가능" items={p.potential_losers} />
                <L title="미확인 가정" items={p.unconfirmed_assumptions} />
                <L title="반대 근거/리스크" items={p.risks} />
                <L title="다음 분기 확인 지표" items={p.next_quarter_checkpoints} />
              </div>
            </div>
          );
        })}
        {data && data.investment_themes.length === 0 && (
          <p className="text-sm text-slate-500">아직 투자 테마가 없습니다. 마켓 테마 화면에서 분석을 실행하세요.</p>
        )}
      </div>
    </div>
  );
}

function L({ title, items }: { title: string; items?: string[] }) {
  const list = items ?? [];
  return (
    <div>
      <p className="font-medium text-slate-500">{title}</p>
      {list.length ? (
        <ul className="ml-4 list-disc text-slate-600">{list.map((x, i) => <li key={i}>{x}</li>)}</ul>
      ) : (
        <p className="text-slate-300">—</p>
      )}
    </div>
  );
}
