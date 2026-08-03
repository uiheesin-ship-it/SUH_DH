"use client";
import { useState } from "react";

import { useEvidence } from "@/lib/hooks";

const STATUS_KO: Record<string, string> = {
  "Confirmed Acceleration": "가속 확인",
  "Narrative Ahead of Numbers": "내러티브가 숫자를 앞섬",
  "Conservative or Underpromising": "보수적/언더프로미스",
  "Mixed Signals": "혼재 신호",
  "Confirmed Deterioration": "악화 확인",
};

export function MaturityBanner({ label }: { label?: string | null }) {
  if (!label) return null;
  return (
    <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
      ⚠️ {label} — 6개 기업 MVP는 파이프라인 검증용입니다. 밸류체인 내 복수 기업이 확보되기 전에는
      High Conviction 테마를 생성하지 않습니다.
    </div>
  );
}

export function ExperimentalTag() {
  return <span className="badge bg-slate-100 text-slate-500">Experimental</span>;
}

export function ScoreBadge({ label, score, status }: { label: string; score: number | null | undefined; status?: string }) {
  const insufficient = score == null || status === "data_insufficient";
  return (
    <span className={`badge ${insufficient ? "bg-slate-100 text-slate-400" : "bg-emerald-50 text-emerald-700"}`}>
      {label}: {insufficient ? "Data Insufficient" : score}
    </span>
  );
}

export function ConfirmationStatus({ status }: { status?: string | null }) {
  if (!status) return null;
  return <span className="pill">{STATUS_KO[status] ?? status}</span>;
}

export function ConvictionBadge({ v }: { v: string }) {
  const map: Record<string, string> = { high: "bg-emerald-100 text-emerald-700", medium: "bg-amber-100 text-amber-700", low: "bg-slate-100 text-slate-500" };
  const ko: Record<string, string> = { high: "높음", medium: "중간", low: "낮음" };
  return <span className={`badge ${map[v] ?? "bg-slate-100"}`}>Conviction: {ko[v] ?? v}</span>;
}

// Evidence toggle: fetches verified/needs-review evidence for a claim on demand.
export function EvidenceToggle({ claimType, claimId }: { claimType: string; claimId: number }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useEvidence(claimType, claimId, open);
  return (
    <div className="mt-2">
      <button onClick={() => setOpen((o) => !o)} className="text-xs text-blue-600 hover:underline">
        {open ? "근거 숨기기" : "근거 보기 (영어 원문)"}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {isLoading && <p className="text-xs text-slate-400">불러오는 중…</p>}
          {data?.evidence.map((e, i) => (
            <blockquote key={i} className="border-l-2 border-slate-300 pl-3 text-xs text-slate-600">
              <span className="mr-2 font-mono text-[10px] text-slate-400">{e.paragraph_id}</span>
              <span className={`badge ${e.verification_status === "verified" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                {e.verification_status ?? "?"}
              </span>
              <p className="mt-1 italic">“{e.exact_quote_en}”</p>
            </blockquote>
          ))}
          {data && data.evidence.length === 0 && (
            <p className="text-xs text-slate-400">연결된 근거가 없습니다 (insufficient_evidence).</p>
          )}
        </div>
      )}
    </div>
  );
}
