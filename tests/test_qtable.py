"""Offline tests for the quarterly guidance/consensus/actual table (app.qtable).

No network: the fetch layer is either stubbed with tiny fake frames or skipped
entirely (SUH_DH_DEMO), so these cover the parts that actually carry risk —
fiscal-quarter math, the curated overlay's placement rules, unit handling and
the exported grid.
"""

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app import qtable  # noqa: E402


# --------------------------------------------------------------------------- #
# 회계 분기 계산
# --------------------------------------------------------------------------- #
def test_period_from_end_march_fiscal_year():
    # 디지털터빈(3월 결산): 2026-03 마감 = FY26 4Q, 2026-06 마감 = FY27 1Q.
    assert qtable.period_from_end(date(2026, 3, 31), 3) == (2026, 4)
    assert qtable.period_from_end(date(2026, 6, 30), 3) == (2027, 1)
    assert qtable.period_from_end(date(2025, 12, 31), 3) == (2026, 3)
    assert qtable.period_from_end(date(2025, 9, 30), 3) == (2026, 2)


def test_period_from_end_december_and_january_fiscal_years():
    assert qtable.period_from_end(date(2026, 3, 31), 12) == (2026, 1)
    assert qtable.period_from_end(date(2026, 12, 31), 12) == (2026, 4)
    # 1월 결산(엔비디아형): 2025-10 마감 = FY26 3Q.
    assert qtable.period_from_end(date(2025, 10, 31), 1) == (2026, 3)
    assert qtable.period_from_end(date(2026, 1, 25), 1) == (2026, 4)


def test_quarter_end_roundtrips_with_period_from_end():
    for fy_end in (1, 3, 6, 9, 12):
        for fy in (2025, 2026):
            for fq in (1, 2, 3, 4):
                end = qtable.quarter_end(fy, fq, fy_end)
                assert qtable.period_from_end(end, fy_end) == (fy, fq)


def test_effective_month_handles_52_week_calendars():
    # 7월 3일 마감(52/53주 달력)은 6월 마감으로 본다.
    assert qtable.period_from_end(date(2026, 7, 3), 3) == (2027, 1)


def test_period_from_report_maps_report_date_to_the_quarter_it_covers():
    # 3월 결산: 8월 초 발표 = 6월 마감 분기(FY27 1Q), 5월 발표 = 3월 마감(FY26 4Q).
    assert qtable.period_from_report(date(2026, 8, 6), 3) == (2027, 1)
    assert qtable.period_from_report(date(2026, 5, 20), 3) == (2026, 4)
    # 분기 마감 직후(2주) 발표도 그 분기로.
    assert qtable.period_from_report(date(2026, 4, 14), 3) == (2026, 4)
    # 12월 결산: 1월 말 발표 = 직전 12월 마감 분기.
    assert qtable.period_from_report(date(2026, 1, 28), 12) == (2025, 4)


def test_quarter_index_arithmetic():
    assert qtable.from_index(qtable.q_index(2026, 4) + 1) == (2027, 1)
    assert qtable.from_index(qtable.q_index(2027, 1) - 6) == (2025, 3)


def test_parse_period_accepts_the_formats_the_curation_file_uses():
    for text in ("FY2026Q4", "2026Q4", "2026 4Q", "FY26 4Q", "fy2026q4"):
        assert qtable.parse_period(text) == (2026, 4), text
    assert qtable.parse_period("FY2027") is None      # 연간은 분기가 아니다
    assert qtable.parse_period("nonsense") is None
    assert qtable.parse_fy("FY2027") == 2027
    assert qtable.parse_fy("FY27") == 2027
    assert qtable.fy_label(2027) == "FY27"


# --------------------------------------------------------------------------- #
# 큐레이션 오버레이
# --------------------------------------------------------------------------- #
def test_quarter_guidance_lands_in_both_past_guidance_and_fwd_qoq():
    idx = qtable._index_curated([{
        "kind": "quarter_guidance", "metric": "revenue",
        "for": "FY2026Q4", "given_at": "FY2026Q3", "low": 130.3, "high": 135.3,
    }])
    assert set(idx) == {
        ("past_guidance", "revenue", qtable.q_index(2026, 4)),
        ("fwd_qoq", "revenue", qtable.q_index(2026, 3)),
    }
    entry = idx[("past_guidance", "revenue", qtable.q_index(2026, 4))]
    assert entry["value"] == pytest.approx(132.8)   # 밴드 중앙값


def test_sections_field_restricts_placement():
    idx = qtable._index_curated([{
        "kind": "quarter_guidance", "metric": "eps",
        "given_at": "FY2027Q1", "text": "미제공", "sections": ["fwd_qoq"],
    }])
    assert list(idx) == [("fwd_qoq", "eps", qtable.q_index(2027, 1))]


def test_units_are_normalized_to_millions():
    idx = qtable._index_curated([
        {"kind": "actual", "metric": "revenue", "for": "FY2026Q4",
         "value": 1.5, "unit": "B_USD"},
        {"kind": "actual", "metric": "eps", "for": "FY2026Q4",
         "value": 0.16, "unit": "USD"},
    ])
    assert idx[("actual", "revenue", qtable.q_index(2026, 4))]["value"] == 1500.0
    assert idx[("actual", "eps", qtable.q_index(2026, 4))]["value"] == 0.16  # 주당은 그대로


def test_bad_entries_are_skipped_not_fatal():
    assert qtable._index_curated([{}, {"kind": "actual"}, {"metric": "revenue"},
                                  {"kind": "nope", "metric": "revenue", "for": "FY2026Q4"},
                                  "not-a-dict"]) == {}


# --------------------------------------------------------------------------- #
# 표 조립 (큐레이션만, 네트워크 없음)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def demo_env(monkeypatch):
    monkeypatch.setenv("SUH_DH_DEMO", "1")


def _find(table, section_key, metric_key):
    section = next(s for s in table["sections"] if s["key"] == section_key)
    row = next(r for r in section["rows"] if r["key"] == metric_key)
    return {c["label"]: cell for c, cell in zip(table["columns"], row["cells"])}


def test_apps_table_reproduces_the_curated_sheet(demo_env):
    table = qtable.build_table("APPS")

    # 최근 발표 분기가 기준점이고, 열은 과거 6 + 향후 4 = 10개.
    assert table["anchor"]["label"] == "2027 1Q"
    assert len(table["columns"]) == 10
    assert [c["label"] for c in table["columns"]][:2] == ["2025 4Q", "2026 1Q"]
    assert [c["label"] for c in table["columns"]][-1] == "2028 1Q"
    assert [c["label"] for c in table["columns"] if c["status"] == "upcoming"] == \
        ["2027 2Q", "2027 3Q", "2027 4Q", "2028 1Q"]
    assert table["fy_end_month"] == 3

    assert _find(table, "past_guidance", "revenue")["2026 4Q"]["text"] == "130.3~135.3"
    assert _find(table, "past_guidance", "revenue")["2027 1Q"]["text"] == "연간 제공"
    assert _find(table, "consensus", "revenue")["2026 4Q"]["text"] == "133.2"
    assert _find(table, "consensus", "eps")["2027 1Q"]["text"] == "0.14"
    assert _find(table, "actual", "revenue")["2027 1Q"]["text"] == "166"
    assert _find(table, "actual", "ebitda")["2026 4Q"]["text"] == "31.4"
    assert _find(table, "actual", "eps")["2026 4Q"]["text"] == "0.16"
    assert _find(table, "fwd_annual", "revenue")["2026 4Q"]["text"] == "FY27 630~650"
    assert _find(table, "fwd_annual", "eps")["2026 4Q"]["text"] == "미제공"
    assert _find(table, "fwd_qoq", "revenue")["2027 1Q"]["text"] == "미제공"
    # QoQ 가이던스는 제시한 분기 칸에도 자동으로 들어간다(같은 사실, 다른 자리).
    assert _find(table, "fwd_qoq", "revenue")["2026 3Q"]["text"] == "130.3~135.3"


def test_unknown_ticker_still_produces_an_empty_grid(demo_env):
    table = qtable.build_table("ZZZZ")
    assert table["curated"] is False
    assert len(table["columns"]) == 10
    assert [s["key"] for s in table["sections"]] == qtable.SECTION_KEYS
    assert all(len(r["cells"]) == 10 for s in table["sections"] for r in s["rows"])
    assert table["filled_cells"] == 0


def test_past_and_ahead_are_configurable(demo_env):
    table = qtable.build_table("APPS", past=2, ahead=1)
    assert [c["label"] for c in table["columns"]] == ["2026 4Q", "2027 1Q", "2027 2Q"]


def test_grid_layout_matches_the_spreadsheet(demo_env):
    table = qtable.build_table("APPS")
    grid = qtable.to_grid(table)
    assert grid[0][0] == "" and grid[0][1] == "2025"
    assert grid[1][1] == "4Q"
    assert grid[2][0] == "과거 가이던스"
    assert grid[3][0].strip() == "매출"
    # 섹션 5개 × (헤더 1 + 지표 4) + 연/분기 헤더 2줄
    assert len(grid) == 2 + len(qtable.SECTIONS) * (1 + len(qtable.METRICS))
    assert all(len(row) == 1 + len(table["columns"]) for row in grid)

    tsv = qtable.to_delimited(table, "\t")
    assert tsv.splitlines()[1].split("\t") == ["", "4Q", "1Q", "2Q", "3Q", "4Q",
                                               "1Q", "2Q", "3Q", "4Q", "1Q"]
    csv = qtable.to_delimited(table, ",")
    assert csv.splitlines()[0].startswith(",2025,")


def test_curation_file_is_valid_and_placeable():
    """data/guidance_table.json 이 스키마대로 읽히는지(오타 조기 발견)."""
    raw = json.loads(open(qtable.QTABLE_FILE, encoding="utf-8").read())
    for ticker, block in raw.items():
        if ticker.startswith("_"):
            continue
        meta, entries = qtable._ticker_block(ticker)
        assert entries, f"{ticker} 엔트리가 비어 있습니다"
        placed = qtable._index_curated(entries)
        assert len(placed) >= len(entries), f"{ticker} 배치되지 않은 엔트리가 있습니다"


# --------------------------------------------------------------------------- #
# 야후 수집 계층 (가짜 프레임)
# --------------------------------------------------------------------------- #
class _FakeSeries(dict):
    """DataFrame 한 행 흉내 — .get(col) 만 쓰므로 dict 로 충분."""


class _FakeFrame:
    def __init__(self, rows: dict, columns: list):
        self._rows = rows
        self.columns = columns
        self.index = list(rows)
        self.empty = not rows

    @property
    def loc(self):
        return self._rows


def test_statement_rows_are_converted_to_millions_and_ebitda_derived():
    cols = [date(2026, 3, 31), date(2025, 12, 31)]
    frame = _FakeFrame({
        "Total Revenue": _FakeSeries({cols[0]: 142_500_000.0, cols[1]: 119_000_000.0}),
        "Operating Income": _FakeSeries({cols[0]: 10_500_000.0, cols[1]: 8_000_000.0}),
        "Reconciled Depreciation": _FakeSeries({cols[0]: 20_900_000.0, cols[1]: 20_000_000.0}),
        "Diluted EPS": _FakeSeries({cols[0]: 0.11, cols[1]: 0.05}),
    }, cols)

    class _Tk:
        quarterly_income_stmt = frame
        income_stmt = frame
        info = {"lastFiscalYearEnd": None}

    out = qtable._fetch_statements(_Tk())
    assert out["fy_end_month"] == 3          # 재무제표 열에서 결산월 추정
    q = out["quarters"][(2026, 4)]
    assert q["revenue"]["value"] == pytest.approx(142.5)
    assert q["operating_income"]["value"] == pytest.approx(10.5)
    assert q["ebitda"]["value"] == pytest.approx(31.4)   # 영업이익 + 감가상각
    assert q["ebitda"]["source"] == "derived"
    assert q["eps"]["value"] == pytest.approx(0.11)      # EPS 는 환산하지 않는다


def test_earnings_dates_are_mapped_to_fiscal_quarters():
    idx = [date(2026, 8, 6), date(2026, 5, 20)]
    frame = _FakeFrame({}, ["EPS Estimate", "Reported EPS"])
    frame.index = idx
    frame._rows = {
        idx[0]: _FakeSeries({"EPS Estimate": 0.14, "Reported EPS": 0.19}),
        idx[1]: _FakeSeries({"EPS Estimate": 0.08, "Reported EPS": 0.16}),
    }
    frame.empty = False

    class _Tk:
        def get_earnings_dates(self, limit=24):
            return frame

    out = qtable._fetch_earnings_dates(_Tk(), 3)
    assert out[(2027, 1)]["eps_actual"] == 0.19
    assert out[(2027, 1)]["eps_consensus"] == 0.14
    assert out[(2026, 4)]["eps_actual"] == 0.16
    assert out[(2026, 4)]["report_date"] == "2026-05-20"


def test_auto_cells_fill_actuals_and_forward_consensus():
    anchor = qtable.q_index(2027, 1)
    fetched = {
        "quarters": {(2027, 1): {"revenue": {"value": 166.0, "source": "yfinance"}}},
        "earnings": {(2027, 1): {"eps_actual": 0.19, "eps_consensus": 0.14}},
        "forward": {"revenue": {"0q": 172.0, "+1q": 180.0}, "eps": {"0q": 0.2}},
    }
    cell = qtable._auto_cell("actual", "revenue", anchor, fetched, anchor, 1.0)
    assert cell["text"] == "166" and cell["source"] == "yfinance"
    assert qtable._auto_cell("consensus", "eps", anchor, fetched, anchor, 1.0)["text"] == "0.14"
    # 0q = 진행 중인 분기(기준 분기 + 1), +1q = 그 다음 분기.
    assert qtable._auto_cell("consensus", "revenue", anchor + 1, fetched, anchor, 1.0)["text"] == "172"
    assert qtable._auto_cell("consensus", "revenue", anchor + 2, fetched, anchor, 1.0)["text"] == "180"
    assert qtable._auto_cell("consensus", "revenue", anchor + 3, fetched, anchor, 1.0) is None
    # 가이던스는 자동 수집 대상이 아니다(큐레이션 전용).
    assert qtable._auto_cell("fwd_annual", "revenue", anchor, fetched, anchor, 1.0) is None


def test_curated_values_win_over_fetched_ones(monkeypatch):
    """같은 칸에 야후 값과 큐레이션 값이 있으면 큐레이션(non-GAAP)이 이긴다."""
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)
    monkeypatch.setattr(qtable, "_fetch_all", lambda ticker: {
        "fy_end_month": 3,
        # 야후 GAAP 매출은 다른 값 — 큐레이션 142.5 가 이겨야 한다.
        "quarters": {(2026, 4): {"revenue": {"value": 140.0, "source": "yfinance"}},
                     (2027, 1): {"revenue": {"value": 160.0, "source": "yfinance"}}},
        "earnings": {(2027, 1): {"eps_actual": 0.11, "eps_consensus": 0.14,
                                 "report_date": "2026-08-06"}},
        "forward": {"revenue": {"0q": 172.0}, "eps": {}},
        "name": "Digital Turbine", "currency": "USD",
    })
    table = qtable.build_table("APPS")
    assert table["anchor"]["report_date"] == "2026-08-06"
    assert _find(table, "actual", "revenue")["2026 4Q"]["text"] == "142.5"
    assert _find(table, "actual", "revenue")["2026 4Q"]["source"] == "curated"
    # 큐레이션이 없는 칸은 야후 값으로 채워진다.
    assert _find(table, "consensus", "revenue")["2027 2Q"]["text"] == "172"


def test_fetch_failure_still_renders_the_curated_table(monkeypatch):
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)

    def _boom(ticker):
        raise RuntimeError("yahoo blocked")

    monkeypatch.setattr(qtable, "_fetch_all", _boom)
    table = qtable.build_table("APPS")
    assert table["fetch_error"] == "yahoo blocked"
    assert _find(table, "actual", "revenue")["2027 1Q"]["text"] == "166"


def test_display_unit_switches_to_billions_for_large_revenue(demo_env):
    quarters = {(2026, 4): {"revenue": {"value": 45_000.0}}}
    assert qtable._pick_unit(quarters, {}) == ("B", 0.001, "십억")
    assert qtable._pick_unit(quarters, {"display_unit": "M"}) == ("M", 1.0, "백만")
    assert qtable._pick_unit({(2026, 4): {"revenue": {"value": 142.5}}}, {})[0] == "M"
