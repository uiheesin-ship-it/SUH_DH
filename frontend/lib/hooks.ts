// TanStack Query hooks over the validated API client.
"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "./api";
import {
  CompaniesResponse,
  CompanyDetail,
  Coverage,
  EvidenceResponse,
  InvestmentThemesResponse,
  ThemesResponse,
  Usage,
} from "./schemas";

const B = "/api/eai";

export const useThemes = () =>
  useQuery({ queryKey: ["themes"], queryFn: () => api.get(`${B}/themes`, ThemesResponse) });

export const useCompanies = () =>
  useQuery({ queryKey: ["companies"], queryFn: () => api.get(`${B}/companies`, CompaniesResponse) });

export const useCompany = (ticker: string) =>
  useQuery({
    queryKey: ["company", ticker],
    queryFn: () => api.get(`${B}/companies/${ticker}`, CompanyDetail),
    enabled: !!ticker,
  });

export const useInvestmentThemes = () =>
  useQuery({
    queryKey: ["ideas"],
    queryFn: () => api.get(`${B}/investment-themes`, InvestmentThemesResponse),
  });

export const useEvidence = (claimType: string, claimId: number, on: boolean) =>
  useQuery({
    queryKey: ["evidence", claimType, claimId],
    queryFn: () => api.get(`${B}/evidence/${claimType}/${claimId}`, EvidenceResponse),
    enabled: on,
  });

export const useUsage = () =>
  useQuery({ queryKey: ["usage"], queryFn: () => api.get(`${B}/usage`, Usage) });

export const useCoverage = () =>
  useQuery({ queryKey: ["coverage"], queryFn: () => api.get(`${B}/coverage`, Coverage) });

export function useRunBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post(`${B}/jobs/run-batch?wait=true`, z.object({ job_id: z.number(), result: z.any() })),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useSeed() {
  return useMutation({
    mutationFn: () => api.post(`${B}/seed`, z.object({ seeded: z.array(z.string()) })),
  });
}
