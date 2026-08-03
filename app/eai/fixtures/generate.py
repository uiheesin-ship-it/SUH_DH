"""Generate synthetic MVP fixtures for the 6 companies × 2 quarters (spec §23).

These are *synthetic* transcripts (no real transcript is redistributed, spec
§6.1) crafted so the pipeline has topic keywords and numeric quotes to work
with. Run:  python -m app.eai.fixtures.generate
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
T_DIR = HERE / "transcripts"
F_DIR = HERE / "financials"

# company -> quarter -> narrative snippets (CEO prepared, CFO prepared, analyst Q, CFO answer)
DATA = {
    "NVDA": {
        "name": "NVIDIA Corporation", "sector": "Technology",
        "2026Q1": {
            "call_date": "2026-02-26",
            "ceo": "Data center demand was exceptional this quarter and we remain supply constrained on our latest AI accelerator platform. Customer demand for AI compute continues to accelerate.",
            "cfo": "Revenue was $26.0 billion, up 78% year over year. Data center revenue set a record. We expect strong demand to continue into next quarter.",
            "q": "Can you talk about HBM supply and networking bottleneck?",
            "a": "HBM supply remains tight and networking is a bottleneck, but supply is improving. Gross margin was 75%.",
        },
        "2026Q2": {
            "call_date": "2026-05-28",
            "ceo": "Data center demand accelerated further and AI adoption is broadening across enterprises. We are still supply constrained but adding capacity.",
            "cfo": "Revenue was $30.0 billion, up 122% year over year, another record. We expect data center investment to remain robust and raised our guidance.",
            "q": "How is HBM supply and pricing trending?",
            "a": "HBM supply is improving into next quarter and pricing power remains strong. Gross margin expanded to 76%.",
        },
    },
    "MSFT": {
        "name": "Microsoft Corporation", "sector": "Technology",
        "2026Q1": {
            "call_date": "2026-01-28",
            "ceo": "Cloud demand was strong and AI adoption across Copilot is accelerating. We are increasing capital expenditure to meet AI compute demand.",
            "cfo": "Revenue grew 16% year over year. Azure growth was strong. Capital expenditure rose to support data center investment. We expect cloud demand to stay healthy.",
            "q": "How should we think about capex and cloud optimization?",
            "a": "Capital expenditure will remain elevated for data center investment. Some customers continue cloud optimization but demand is robust.",
        },
        "2026Q2": {
            "call_date": "2026-04-29",
            "ceo": "AI adoption accelerated and data center investment increased again to meet strong demand. Power demand for our data centers is a growing focus.",
            "cfo": "Revenue grew 18% year over year. Azure demand was exceptional and we raised capital expenditure guidance for data center investment.",
            "q": "Is power demand a constraint on data center investment?",
            "a": "Power demand is a real constraint and we are investing in supply. Cloud demand remains strong with pricing power intact.",
        },
    },
    "JPM": {
        "name": "JPMorgan Chase & Co.", "sector": "Financial",
        "2026Q1": {
            "call_date": "2026-01-14",
            "ceo": "The consumer remains healthy overall though we see early signs of credit normalization. Loan growth was modest.",
            "cfo": "Net interest income was strong. Charge-offs ticked up and we increased credit provision. Consumer spending was resilient. NIM was stable.",
            "q": "Are you seeing consumer weakness or rising delinquency?",
            "a": "Delinquency rose modestly and we are watching credit deterioration in lower-income segments. Overall the consumer is still healthy.",
        },
        "2026Q2": {
            "call_date": "2026-04-11",
            "ceo": "Consumer health softened slightly and credit normalization continued. We remain well reserved.",
            "cfo": "Charge-offs increased again and credit provision rose. Delinquency trends worsened modestly. Loan growth was subdued and NIM compressed.",
            "q": "How concerned are you about credit deterioration and delinquency?",
            "a": "Credit deterioration is gradual, not alarming. Delinquency is rising in cards. We increased provisions as a precaution.",
        },
    },
    "WMT": {
        "name": "Walmart Inc.", "sector": "Consumer Defensive",
        "2026Q1": {
            "call_date": "2026-02-20",
            "ceo": "Traffic was strong and we saw continued trade-down from higher-income shoppers. Consumer demand held up.",
            "cfo": "Comparable sales grew 4%. We managed inventory well with some destocking. Pricing was competitive with promotional activity in discretionary categories.",
            "q": "Are you seeing consumer weakness or more trade-down?",
            "a": "We see trade-down and value-seeking behavior, a sign of consumer caution. Inventory is healthy after destocking.",
        },
        "2026Q2": {
            "call_date": "2026-05-15",
            "ceo": "Traffic accelerated and trade-down continued as consumers seek value. Grocery demand was strong.",
            "cfo": "Comparable sales grew 5%. Inventory destocking is complete and inventory is lean. Promotional activity increased in discretionary spending categories.",
            "q": "How is discretionary spending and pricing trending?",
            "a": "Discretionary spending remains soft, a sign of consumer weakness, but our pricing power in grocery is strong.",
        },
    },
    "CAT": {
        "name": "Caterpillar Inc.", "sector": "Industrials",
        "2026Q1": {
            "call_date": "2026-01-30",
            "ceo": "Order growth was solid and backlog increased. Demand for construction equipment was strong in North America.",
            "cfo": "Backlog rose to a record. Book-to-bill was above one. Pricing more than offset cost inflation. Dealer inventory normalized.",
            "q": "How is backlog and dealer inventory trending?",
            "a": "Backlog grew and dealer inventory is healthy. Order growth remains strong though lead times are shortening.",
        },
        "2026Q2": {
            "call_date": "2026-04-30",
            "ceo": "Order growth moderated but backlog remains elevated. Demand for power generation equipment tied to data center investment accelerated.",
            "cfo": "Backlog was stable. Book-to-bill was near one. Pricing power held versus cost. Dealer inventory ticked up slightly.",
            "q": "Is demand weakening or is this normal seasonality?",
            "a": "Demand is healthy overall; the moderation is seasonal. Data center-driven power demand is a new growth driver.",
        },
    },
    "XOM": {
        "name": "Exxon Mobil Corporation", "sector": "Energy",
        "2026Q1": {
            "call_date": "2026-01-31",
            "ceo": "Production grew and we maintained capital expenditure discipline. Commodity prices were volatile.",
            "cfo": "Upstream volumes rose. Capital expenditure was in line with plan. Pricing followed commodity markets. Margins were pressured by lower crude.",
            "q": "How are you thinking about capex and commodity price exposure?",
            "a": "Capital expenditure is disciplined. Commodity price weakness pressured margins but our cost position is strong.",
        },
        "2026Q2": {
            "call_date": "2026-05-02",
            "ceo": "Production increased again and we kept capital expenditure disciplined despite commodity price weakness.",
            "cfo": "Upstream volumes grew. Capital expenditure was steady. Lower commodity prices weighed on realizations though cost control helped margins.",
            "q": "Will you cut capex if commodity prices stay weak?",
            "a": "We will maintain capital expenditure discipline through the cycle. Commodity price weakness is manageable given our low cost base.",
        },
    },
}


def _sections(q: dict) -> list[dict]:
    return [
        {"section_type": "prepared_remarks", "turns": [
            {"speaker_name": "Operator", "speaker_role": "operator",
             "text": "Good day and welcome to the earnings conference call."},
            {"speaker_name": "CEO", "speaker_role": "ceo", "text": q["ceo"]},
            {"speaker_name": "CFO", "speaker_role": "cfo", "text": q["cfo"]},
        ]},
        {"section_type": "qa", "turns": [
            {"speaker_name": "Analyst", "speaker_role": "analyst",
             "speaker_company": "Research Partners", "text": q["q"]},
            {"speaker_name": "CFO", "speaker_role": "cfo", "text": q["a"]},
        ]},
    ]


# verified KPI + guidance per company/quarter (synthetic but internally consistent)
FIN = {
    "NVDA": {"FY2026Q1": {"rev_g": 0.78, "gm": 0.75, "gmid": 28.0, "cons": 26.5},
             "FY2026Q2": {"rev_g": 1.22, "gm": 0.76, "gmid": 33.0, "cons": 30.0}},
    "MSFT": {"FY2026Q1": {"rev_g": 0.16, "gm": 0.70, "gmid": 64.0, "cons": 63.0},
             "FY2026Q2": {"rev_g": 0.18, "gm": 0.70, "gmid": 66.0, "cons": 64.0}},
    "JPM": {"FY2026Q1": {"rev_g": 0.05, "gm": 0.0, "gmid": None, "cons": None},
            "FY2026Q2": {"rev_g": -0.02, "gm": 0.0, "gmid": None, "cons": None}},
    "WMT": {"FY2026Q1": {"rev_g": 0.04, "gm": 0.245, "gmid": None, "cons": None},
            "FY2026Q2": {"rev_g": 0.05, "gm": 0.246, "gmid": None, "cons": None}},
    "CAT": {"FY2026Q1": {"rev_g": 0.06, "gm": 0.30, "gmid": 17.0, "cons": 16.5},
            "FY2026Q2": {"rev_g": 0.02, "gm": 0.30, "gmid": 16.5, "cons": 16.6}},
    "XOM": {"FY2026Q1": {"rev_g": -0.03, "gm": 0.12, "gmid": None, "cons": None},
            "FY2026Q2": {"rev_g": -0.05, "gm": 0.11, "gmid": None, "cons": None}},
}


def _financials(ticker: str) -> dict:
    kpis, guidance = [], []
    for period, f in FIN[ticker].items():
        kpis.append({"fiscal_period": period, "metric_id": "revenue",
                     "metric_name": "Total revenue", "value": None, "unit": "B_USD",
                     "actual_or_guidance": "actual", "yoy_growth": f["rev_g"],
                     "verification_status": "verified", "source_page": "PR-1"})
        kpis.append({"fiscal_period": period, "metric_id": "gross_margin",
                     "metric_name": "Gross margin", "value": f["gm"], "unit": "pct",
                     "actual_or_guidance": "actual", "yoy_growth": None,
                     "verification_status": "verified", "source_page": "PR-2"})
        kpis.append({"fiscal_period": period, "metric_id": "op_metric",
                     "metric_name": "Operating KPI", "value": 1.0, "unit": "x",
                     "actual_or_guidance": "actual", "yoy_growth": f["rev_g"] * 0.8,
                     "verification_status": "verified", "source_page": "PR-3"})
        if f["gmid"] is not None:
            guidance.append({"fiscal_period": period, "metric": "revenue", "unit": "B_USD",
                             "guidance_mid": f["gmid"], "consensus": f["cons"],
                             "verification_status": "verified",
                             "sources": ["synthetic://fixture"]})
    return {"ticker": ticker, "kpis": kpis, "guidance": guidance}


def main() -> None:
    T_DIR.mkdir(parents=True, exist_ok=True)
    F_DIR.mkdir(parents=True, exist_ok=True)
    for ticker, meta in DATA.items():
        for qkey in ("2026Q1", "2026Q2"):
            if qkey not in meta:
                continue
            q = meta[qkey]
            fy, fq = 2026, int(qkey[-1])
            doc = {"ticker": ticker, "company": meta["name"], "sector": meta["sector"],
                   "fiscal_year": fy, "fiscal_quarter": fq, "calendar_year": fy,
                   "calendar_quarter": fq, "call_date": q["call_date"],
                   "published_at": q["call_date"], "language": "en",
                   "sections": _sections(q)}
            (T_DIR / f"{ticker}_{fy}Q{fq}.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        (F_DIR / f"{ticker}.json").write_text(
            json.dumps(_financials(ticker), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote fixtures to {T_DIR} and {F_DIR}")


if __name__ == "__main__":
    main()
