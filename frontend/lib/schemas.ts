// Zod schemas validating the FastAPI /api/eai responses (spec: Zod validation).
// The UI is Korean; analysis fields stay English-first (evidence quotes, topics).
import { z } from "zod";

export const ScoreBreakdown = z.object({
  score: z.number().nullable(),
  status: z.string().optional(),
  is_experimental: z.boolean().optional(),
  components: z.record(z.any()).optional(),
  weights: z.record(z.any()).optional(),
  missing_component_count: z.number().optional(),
});

export const CallScores = z.object({
  narrative_momentum: ScoreBreakdown.optional(),
  fundamental_confirmation: ScoreBreakdown.optional(),
  narrative_confirmation_status: z.string().optional(),
  score_version: z.string().optional(),
  is_experimental: z.boolean().optional(),
  verified_kpi_count: z.number().optional(),
});

export const Company = z.object({
  ticker: z.string(),
  name: z.string(),
  sector: z.string().nullable().optional(),
  industry: z.string().nullable().optional(),
  universe_type: z.string().nullable().optional(),
  signal_roles: z.array(z.string()).default([]),
  value_chain_positions: z.array(z.string()).default([]),
});
export const CompaniesResponse = z.object({ companies: z.array(Company) });

export const CompanyCall = z.object({
  fiscal_year: z.number(),
  fiscal_quarter: z.number(),
  summary: z.record(z.any()),
  scores: CallScores.nullable().optional(),
});
export const CompanyDetail = Company.extend({
  calls: z.array(CompanyCall).default([]),
  quarterly_comparisons: z.array(z.record(z.any())).default([]),
});

export const Theme = z.object({
  theme_id: z.string(),
  theme_name_en: z.string(),
  theme_name_ko: z.string(),
  theme_score: z.number().nullable(),
  score_status: z.string().optional(),
  is_experimental: z.boolean().optional(),
  maturity_label: z.string().nullable().optional(),
  payload: z.record(z.any()).optional(),
});
export const ThemesResponse = z.object({
  themes: z.array(Theme),
  maturity: z.string().nullable().optional(),
});

export const InvestmentTheme = z.object({
  investment_theme: z.string(),
  conviction: z.string(),
  narrative_confirmation_status: z.string().nullable().optional(),
  is_experimental: z.boolean().optional(),
  maturity_label: z.string().nullable().optional(),
  payload: z.record(z.any()).optional(),
});
export const InvestmentThemesResponse = z.object({
  investment_themes: z.array(InvestmentTheme),
  maturity: z.string().nullable().optional(),
});

export const Evidence = z.object({
  paragraph_id: z.string(),
  exact_quote_en: z.string(),
  translation_ko: z.string().nullable().optional(),
  verification_status: z.string().nullable().optional(),
  verification_method: z.string().nullable().optional(),
  numeric_check: z.record(z.any()).nullable().optional(),
});
export const EvidenceResponse = z.object({ evidence: z.array(Evidence) });

export const Usage = z.object({
  total_calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  estimated_cost: z.number(),
  cache_hit_rate: z.number(),
  avg_processing_time: z.number(),
  by_model: z.record(z.any()),
});

export const Coverage = z.object({
  total_companies: z.number(),
  by_sector: z.record(z.number()),
  by_signal_role: z.record(z.number()),
  by_value_chain: z.record(z.number()),
  by_universe_type: z.record(z.number()),
  single_company_topics: z.array(z.string()),
  maturity: z.string().nullable().optional(),
});

export type TCompany = z.infer<typeof Company>;
export type TCompanyDetail = z.infer<typeof CompanyDetail>;
export type TTheme = z.infer<typeof Theme>;
export type TInvestmentTheme = z.infer<typeof InvestmentTheme>;
export type TEvidence = z.infer<typeof Evidence>;
