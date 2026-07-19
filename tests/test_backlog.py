"""Offline tests for the DART 수주잔고 (order-backlog) parser (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import dartdoc


# --------------------------------------------------------------------------- #
# amount / unit / period helpers
# --------------------------------------------------------------------------- #
def test_parse_amount():
    assert dartdoc.parse_amount("89,123,400") == 89123400.0
    assert dartdoc.parse_amount("1,234.5") == 1234.5
    assert dartdoc.parse_amount("(1,200)") == -1200.0     # parentheses = negative
    assert dartdoc.parse_amount("-500") == -500.0
    assert dartdoc.parse_amount("₩ 3,000 원") == 3000.0
    assert dartdoc.parse_amount("") is None
    assert dartdoc.parse_amount("-") is None
    assert dartdoc.parse_amount("해당사항 없음") is None


def test_unit_multiplier():
    assert dartdoc.unit_multiplier("백만원") == (1_000_000.0, None)
    assert dartdoc.unit_multiplier("억원") == (100_000_000.0, None)
    assert dartdoc.unit_multiplier("원") == (1.0, None)
    assert dartdoc.unit_multiplier(None) == (1.0, None)
    mult, cur = dartdoc.unit_multiplier("천달러")
    assert cur == "USD"


def test_find_unit():
    assert dartdoc.find_unit("수주현황 (단위 : 백만원)") == "백만원"
    assert dartdoc.find_unit("(단위:억원)") == "억원"
    assert dartdoc.find_unit("표에 단위 없음") is None


def test_period_and_quarter():
    assert dartdoc.report_period("분기보고서 (2025.03)") == "2025-03"
    assert dartdoc.report_period("사업보고서 (2024.12)") == "2024-12"
    assert dartdoc.report_period("반기보고서 (2025.06)") == "2025-06"
    assert dartdoc.period_to_quarter("2025-03") == "2025 1Q"
    assert dartdoc.period_to_quarter("2025-06") == "2025 반기"
    assert dartdoc.period_to_quarter("2024-12") == "2024 연간"


# --------------------------------------------------------------------------- #
# table extraction — realistic DART 수주상황 layouts
# --------------------------------------------------------------------------- #
CONSTRUCTION = """
<p>가. 수주상황 (단위 : 백만원)</p>
<table border="1">
  <tr><th>공사명</th><th>발주처</th><th>계약금액</th><th>기성액</th><th>수주잔고</th></tr>
  <tr><td>A현장</td><td>발주처1</td><td>500,000</td><td>200,000</td><td>300,000</td></tr>
  <tr><td>B현장</td><td>발주처2</td><td>800,000</td><td>100,000</td><td>700,000</td></tr>
  <tr><td>합계</td><td></td><td>1,300,000</td><td>300,000</td><td>1,000,000</td></tr>
</table>
"""

SHIPBUILDING = """
<p>수주잔고 현황 (단위: 억원)</p>
<table>
  <tr><td>구분</td><td>수주총액</td><td>기인식</td><td>수주잔액</td></tr>
  <tr><td>선박</td><td>50,000</td><td>20,000</td><td>30,000</td></tr>
</table>
"""

# A table with a 소계 that must NOT be double-counted, and no explicit 합계.
SUBTOTAL = """
<p>(단위 : 백만원)</p>
<table>
  <tr><th>부문</th><th>수주잔고</th></tr>
  <tr><td>국내</td><td>100,000</td></tr>
  <tr><td>해외</td><td>250,000</td></tr>
  <tr><td>소계</td><td>350,000</td></tr>
</table>
"""

FX = """
<p>Order backlog (단위 : 천달러)</p>
<table>
  <tr><th>Project</th><th>수주잔고</th></tr>
  <tr><td>P1</td><td>1,200,000</td></tr>
</table>
"""

NO_BACKLOG = """
<p>주요 재무현황 (단위 : 백만원)</p>
<table>
  <tr><th>항목</th><th>매출액</th><th>영업이익</th></tr>
  <tr><td>2025</td><td>900,000</td><td>50,000</td></tr>
</table>
"""


def test_extract_construction_total_row():
    r = dartdoc.extract_backlog(CONSTRUCTION)
    assert r is not None
    assert r["method"] == "total-row"
    assert r["unit"] == "백만원"
    assert r["backlog_raw"] == "1,000,000"
    assert r["backlog_krw"] == 1_000_000 * 1_000_000   # 1조원


def test_extract_shipbuilding_single_row_uk_won():
    r = dartdoc.extract_backlog(SHIPBUILDING)
    assert r is not None
    assert r["method"] == "single-row"
    assert r["unit"] == "억원"
    assert r["backlog_krw"] == 30_000 * 100_000_000     # 3조원


def test_extract_subtotal_not_double_counted():
    r = dartdoc.extract_backlog(SUBTOTAL)
    assert r is not None
    # 소계 rows are excluded from the sum, leaving 국내+해외 = 350,000 백만원.
    assert r["backlog_krw"] == 350_000 * 1_000_000


def test_extract_fx_kept_as_currency():
    r = dartdoc.extract_backlog(FX)
    assert r is not None
    assert r["currency"] == "USD"
    assert r["backlog_krw"] is None                     # not converted
    assert r["backlog_raw"] == "1,200,000"


def test_no_backlog_table_returns_none():
    assert dartdoc.extract_backlog(NO_BACKLOG) is None
    assert dartdoc.extract_backlog("<p>본문에 표가 없음</p>") is None


def test_colspan_alignment():
    html = """
    <table>
      <tr><th colspan="2">기본</th><th>수주잔고</th></tr>
      <tr><td>구분</td><td>발주처</td><td>잔고</td></tr>
      <tr><td>계</td><td></td><td>777,000</td></tr>
    </table>
    """
    r = dartdoc.extract_backlog(html)
    assert r is not None
    assert r["backlog_raw"] == "777,000"
