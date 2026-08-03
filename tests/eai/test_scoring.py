"""Offline unit tests for code-computed scores (spec §4, §13, §14, §23)."""

from app.eai.services import scoring


def _mentions(direction, intensity, mgmt=True, role="ceo", section="prepared_remarks",
              forward=True, n=3):
    return [{"direction": direction, "intensity": intensity, "management_initiated": mgmt,
             "speaker_role": role, "section_type": section, "forward_looking": forward}
            for _ in range(n)]


def test_narrative_momentum_strong_vs_weak():
    strong = scoring.narrative_momentum(_mentions("positive", 5))
    weak = scoring.narrative_momentum(_mentions("negative", 1, mgmt=False, role="analyst",
                                                section="qa", forward=False))
    assert strong.score > 0.8
    assert weak.score < 0.3
    assert strong.is_experimental


def test_fundamental_insufficient_when_few_verified_kpis():
    kpis = [{"metric_id": "revenue", "yoy_growth": 0.3, "verification_status": "verified"}]
    fb = scoring.fundamental_confirmation(kpis, [], minimum_verified_kpi_count=3)
    assert fb.status == "data_insufficient"
    assert fb.score is None


def test_fundamental_confirmation_from_verified_numbers():
    kpis = [
        {"metric_id": "revenue", "yoy_growth": 0.30, "verification_status": "verified"},
        {"metric_id": "eps", "yoy_growth": 0.25, "verification_status": "verified"},
        {"metric_id": "orders", "yoy_growth": 0.20, "verification_status": "verified"},
    ]
    guidance = [{"metric": "revenue", "guidance_mid": 33.0, "consensus": 30.0}]
    fb = scoring.fundamental_confirmation(kpis, guidance, minimum_verified_kpi_count=3)
    assert fb.status == "ok"
    assert fb.score > 0.6


def test_classification_matrix():
    strong_n = scoring.ScoreBreakdown(score=0.9)
    weak_n = scoring.ScoreBreakdown(score=0.2)
    strong_f = scoring.ScoreBreakdown(score=0.8)
    weak_f = scoring.ScoreBreakdown(score=0.2)
    assert scoring.classify(strong_n, strong_f)["status"] == "Confirmed Acceleration"
    assert scoring.classify(strong_n, weak_f)["status"] == "Narrative Ahead of Numbers"
    assert scoring.classify(weak_n, strong_f)["status"] == "Conservative or Underpromising"
    assert scoring.classify(weak_n, weak_f)["status"] == "Confirmed Deterioration"


def test_classification_insufficient_fundamental():
    strong_n = scoring.ScoreBreakdown(score=0.9)
    insufficient = scoring.ScoreBreakdown(score=None, status="data_insufficient")
    res = scoring.classify(strong_n, insufficient)
    assert res["fundamental_available"] is False


def test_theme_score_breadth_gate():
    comps = {"breadth": 0.9, "momentum": 0.8, "intensity": 0.7, "persistence": 0.6,
             "value_chain_confirmation": 0.5, "numeric_confirmation": 0.5}
    gated = scoring.theme_score(comps, company_count=2, minimum_company_breadth=3)
    assert gated.status == "data_insufficient"
    ok = scoring.theme_score(comps, company_count=5, minimum_company_breadth=3)
    assert ok.status == "ok"
    assert 0 < ok.score <= 100


def test_theme_score_missing_component_not_inflated():
    comps = {"breadth": 0.9, "momentum": None, "intensity": 0.7, "persistence": 0.6,
             "value_chain_confirmation": 0.5, "numeric_confirmation": 0.5}
    res = scoring.theme_score(comps, company_count=5)
    assert res.status == "data_insufficient"
    assert res.missing_component_count == 1


def test_theme_score_frequency_alone_does_not_max():
    # high momentum/intensity but zero breadth & value-chain & numeric confirmation
    comps = {"breadth": 0.0, "momentum": 1.0, "intensity": 1.0, "persistence": 1.0,
             "value_chain_confirmation": 0.0, "numeric_confirmation": 0.0}
    res = scoring.theme_score(comps, company_count=5)
    # breadth(25)+vcc(15)+numeric(15)=55 pts unavailable → capped well below 100
    assert res.score <= 45


def test_incremental_score_penalizes_redundancy():
    low_redundancy = scoring.incremental_information_score({
        "new_topic_contribution": 1.0, "independent_confirmation": 1.0,
        "existing_universe_redundancy": 0.0, "data_availability_reliability": 1.0,
    })
    high_redundancy = scoring.incremental_information_score({
        "new_topic_contribution": 0.1, "independent_confirmation": 0.1,
        "existing_universe_redundancy": 1.0, "data_availability_reliability": 1.0,
    })
    assert low_redundancy.score > high_redundancy.score
    assert low_redundancy.is_experimental
