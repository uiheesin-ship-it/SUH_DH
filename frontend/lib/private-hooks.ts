"use client";
import { useQuery } from "@tanstack/react-query";

import { apiGet, useAuth } from "./auth";

const B = "/api/eai/private";

export function useCompanies() {
  const { token } = useAuth();
  return useQuery({ queryKey: ["p-companies"], queryFn: () => apiGet(token, `${B}/companies`) });
}

export function usePeriods(ticker: string | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ["p-periods", ticker],
    queryFn: () => apiGet(token, `${B}/periods/${ticker}`),
    enabled: !!ticker,
  });
}

export function useTranscript(ticker: string | null, fy: number | null, fq: number | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ["p-transcript", ticker, fy, fq],
    queryFn: () => apiGet(token, `${B}/transcript/${ticker}/${fy}/${fq}`),
    enabled: !!ticker && !!fy && !!fq,
    retry: false,
  });
}

export function useEvolution(ticker: string | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ["p-evolution", ticker],
    queryFn: () => apiGet(token, `${B}/company/${ticker}/evolution`),
    enabled: !!ticker,
  });
}

export function useInvestmentPoints() {
  const { token } = useAuth();
  return useQuery({
    queryKey: ["p-ideas"],
    queryFn: () => apiGet(token, `${B}/investment-points`),
  });
}

export function useSearch(q: string, ticker: string | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ["p-search", q, ticker],
    queryFn: () => apiGet(token, `${B}/search?q=${encodeURIComponent(q)}${ticker ? `&ticker=${ticker}` : ""}`),
    enabled: q.trim().length > 0,
  });
}

// bundle download → triggers a file save
export async function downloadBundle(token: string | null, tickers: string[], periods: string[],
                                     format: "txt" | "docx") {
  const res = await fetch(`${B}/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ tickers, periods, format }),
  });
  if (!res.ok) throw new Error(`다운로드 실패 (${res.status})`);
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/);
  const name = m ? m[1] : `transcripts.${format}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
