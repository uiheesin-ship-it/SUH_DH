"""Topic Ontology (spec §10) — semantic topics, not keyword strings.

Versioned so past analyses reproduce (``ontology_version``). New topics found
by the LLM are stored as ``new_topic_candidate`` and only promoted after human
approval (handled in the service layer). The default set below is the ``onto1``
version; it can be overridden/extended via eai_config.yaml or the admin UI.
"""

from __future__ import annotations

# category -> list of (topic_id, name_en, name_ko)
_COMMON: dict[str, list[tuple[str, str, str]]] = {
    "demand": [
        ("demand_growth", "Demand Growth", "수요 성장"),
        ("demand_weakness", "Demand Weakness", "수요 약화"),
    ],
    "pricing": [
        ("pricing_power", "Pricing Power", "가격 결정력"),
        ("discounting", "Discounting", "할인/판촉"),
    ],
    "inventory": [
        ("inventory_build", "Inventory Build", "재고 증가"),
        ("inventory_destocking", "Inventory Destocking", "재고 조정"),
    ],
    "supply": [
        ("supply_constraint", "Supply Constraint", "공급 제약"),
        ("supply_normalization", "Supply Normalization", "공급 정상화"),
    ],
    "capex": [
        ("capital_expenditure", "Capital Expenditure", "설비투자"),
        ("data_center_investment", "Data Center Investment", "데이터센터 투자"),
        ("power_demand", "Power Demand", "전력 수요"),
    ],
    "labor": [
        ("hiring", "Hiring", "채용 확대"),
        ("layoffs", "Layoffs", "감원"),
        ("wage_pressure", "Wage Pressure", "임금 상승 압력"),
        ("productivity", "Productivity", "생산성"),
    ],
    "consumer": [
        ("consumer_weakness", "Consumer Weakness", "소비 둔화"),
    ],
    "credit": [
        ("credit_deterioration", "Credit Deterioration", "신용 악화"),
        ("delinquency", "Delinquency", "연체"),
    ],
    "macro": [
        ("interest_rates", "Interest Rates", "금리"),
        ("foreign_exchange", "Foreign Exchange", "환율"),
        ("tariffs", "Tariffs", "관세"),
        ("regulation", "Regulation", "규제"),
        ("geographic_demand", "Geographic Demand", "지역별 수요"),
    ],
    "technology": [
        ("ai_adoption", "AI Adoption", "AI 도입"),
        ("automation", "Automation", "자동화"),
        ("cloud_optimization", "Cloud Optimization", "클라우드 최적화"),
        ("cybersecurity_spending", "Cybersecurity Spending", "사이버보안 지출"),
    ],
}

# industry sub-topics
_SECTOR: dict[str, list[tuple[str, str, str]]] = {
    "semiconductor": [
        ("hbm", "HBM", "고대역폭메모리"),
        ("advanced_packaging", "Advanced Packaging", "첨단 패키징"),
        ("foundry_utilization", "Foundry Utilization", "파운드리 가동률"),
        ("lead_time", "Lead Time", "리드타임"),
        ("wafer_demand", "Wafer Demand", "웨이퍼 수요"),
        ("ai_accelerator_demand", "AI Accelerator Demand", "AI 가속기 수요"),
        ("networking_bottleneck", "Networking Bottleneck", "네트워킹 병목"),
    ],
    "bank": [
        ("nim", "NIM", "순이자마진"),
        ("deposit_beta", "Deposit Beta", "예금 베타"),
        ("charge_off", "Charge-off", "대손상각"),
        ("loan_growth", "Loan Growth", "대출 성장"),
        ("credit_provision", "Credit Provision", "대손충당금"),
    ],
    "consumer_retail": [
        ("traffic", "Traffic", "내점객수"),
        ("ticket_size", "Ticket Size", "객단가"),
        ("promotional_activity", "Promotional Activity", "판촉 활동"),
        ("trade_down", "Trade-down", "저가 전환"),
        ("discretionary_spending", "Discretionary Spending", "재량적 소비"),
    ],
    "industrial": [
        ("order_growth", "Order Growth", "수주 성장"),
        ("backlog", "Backlog", "수주잔고"),
        ("book_to_bill", "Book-to-bill", "수주/매출 비율"),
        ("pricing_vs_cost", "Pricing versus Cost", "가격 대 비용"),
        ("dealer_inventory", "Dealer Inventory", "딜러 재고"),
    ],
}


def _build(version: str = "onto1") -> dict[str, dict]:
    topics: dict[str, dict] = {}
    for category, items in {**_COMMON, **_SECTOR}.items():
        for tid, en, ko in items:
            topics[tid] = {
                "topic_id": tid, "name_en": en, "name_ko": ko,
                "category": category, "ontology_version": version, "status": "active",
            }
    return topics


_TOPICS = _build()


def topics(version: str = "onto1") -> dict[str, dict]:
    return _TOPICS


def get(topic_id: str) -> dict | None:
    return _TOPICS.get(topic_id)


def all_ids() -> list[str]:
    return list(_TOPICS.keys())


def snapshot(version: str = "onto1") -> dict:
    return {"version": version, "topics": _TOPICS}
