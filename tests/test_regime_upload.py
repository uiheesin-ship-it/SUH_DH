"""Manual-upload tests for the Market Regime Lab.

These use real files — the sample CSVs shipped in ``docs/samples/`` and files
written to tmp_path in awkward real-world shapes (Nasdaq's ``$1,234.56`` /
``Close/Last``, Korean headers in cp949, Excel workbooks, Excel serial dates) —
not synthetic in-memory frames, because the failure mode being guarded against
is a parser that only works on tidy data.

The last group is the important one: once loaded, an uploaded dataset must be
*indistinguishable* from a downloaded one to every analysis layer.

Run with:  python -m pytest tests/test_regime_upload.py -q
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.regime import audit, forward, quality, similarity
from app.regime.config import Params, load_config
from app.regime.data import loader, upload
from app.regime.data.sources import synthetic_prices
from app.regime.features import build_features

SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "samples"


@pytest.fixture(scope="module")
def prices():
    return synthetic_prices("^IXIC", "2006-01-01")


def _csv(tmp_path: Path, name: str, text: str, encoding: str = "utf-8") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


# ---------------- reading real-world file shapes ----------------

def test_reads_shipped_sample_files():
    raw = upload.read_table(SAMPLES / "sample_ohlcv.csv", "sample_ohlcv.csv")
    mapping = upload.suggest_mapping(raw.columns)
    assert mapping == {"date": "Date", "open": "Open", "high": "High",
                       "low": "Low", "close": "Close", "volume": "Volume"}
    res = upload.build_prices(raw, mapping, "sample_ohlcv.csv")
    assert res.ok and list(res.frame.columns) == ["open", "high", "low", "close", "volume"]
    assert res.frame.index.is_monotonic_increasing
    assert res.stats["rows"] == 300

    yraw = upload.read_table(SAMPLES / "sample_us10y.csv", "sample_us10y.csv")
    ymap = upload.suggest_mapping(yraw.columns, upload.YIELD_FIELDS)
    assert ymap["date"] == "observation_date" and ymap["yield"] == "DGS10"
    yres = upload.build_yield(yraw, ymap, "sample_us10y.csv")
    assert yres.ok and yres.stats["detected_unit"] == "percent"
    assert 3.5 < float(yres.series.median()) < 4.5

    vraw = upload.read_table(SAMPLES / "sample_volume.csv", "sample_volume.csv")
    vmap = upload.suggest_mapping(vraw.columns, ("date", "volume"))
    assert vmap["date"] == "날짜" and vmap["volume"] == "거래량"
    assert upload.build_volume(vraw, vmap, "sample_volume.csv").ok


def test_parses_nasdaq_style_currency_and_thousands(tmp_path):
    path = _csv(tmp_path, "nasdaq.csv",
                'Date,Close/Last,Volume,Open,High,Low\n'
                '09/12/2025,"$1,234.56","2,345,678",$1230.00,$1240.00,$1225.00\n'
                '09/11/2025,$1220.10,1.2M,$1215.00,$1225.00,$1210.00\n')
    raw = upload.read_table(path, "nasdaq.csv")
    res = upload.build_prices(raw, upload.suggest_mapping(raw.columns), "nasdaq.csv")
    assert res.ok
    assert res.frame.loc["2025-09-12", "close"] == pytest.approx(1234.56)
    assert res.frame.loc["2025-09-11", "volume"] == pytest.approx(1.2e6)
    assert res.frame.index[0] < res.frame.index[1]          # 역순 파일도 정렬된다


def test_parses_korean_headers_in_cp949(tmp_path):
    path = _csv(tmp_path, "kr.csv",
                "날짜,시가,고가,저가,종가,거래량\n"
                "2025-01-02,100,102,99,101,1000000\n"
                "2025-01-03,101,103,100,102,1100000\n", encoding="cp949")
    raw = upload.read_table(path, "kr.csv")
    mapping = upload.suggest_mapping(raw.columns)
    assert mapping["close"] == "종가" and mapping["volume"] == "거래량"
    res = upload.build_prices(raw, mapping, "kr.csv")
    assert res.ok and len(res.frame) == 2


def test_parses_xlsx_with_excel_serial_dates(tmp_path):
    path = tmp_path / "book.xlsx"
    pd.DataFrame({"Date": [45000, 45001, 45002],          # Excel serial
                  "Open": [10, 11, 12], "High": [11, 12, 13], "Low": [9, 10, 11],
                  "Close": [10.5, 11.5, 12.5], "Volume": [100, 200, 300]}).to_excel(path, index=False)
    assert upload.sheet_names(path.read_bytes(), "book.xlsx") == ["Sheet1"]
    raw = upload.read_table(path.read_bytes(), "book.xlsx")
    res = upload.build_prices(raw, upload.suggest_mapping(raw.columns), "book.xlsx")
    assert res.ok
    assert str(res.frame.index[0].date()) == "2023-03-15"


# ---------------- reporting, not silently dropping ----------------

def test_duplicates_and_unparseable_rows_are_reported(tmp_path):
    path = _csv(tmp_path, "messy.csv",
                "Date,Close,Volume\n"
                "2025-01-02,100,1000\n"
                "2025-01-03,bad,2000\n"
                "2025-01-06,,3000\n"
                "2025-01-07,103,4000\n"
                "2025-01-07,104,4100\n"
                "not-a-date,105,5000\n")
    raw = upload.read_table(path, "messy.csv")
    res = upload.build_prices(raw, upload.suggest_mapping(raw.columns), "messy.csv")
    msgs = " ".join(i.message for i in res.issues)
    assert "날짜를 해석할 수 없는 행 1개" in msgs
    assert "필수 값이 비어 있는 행 2개" in msgs
    assert "중복 날짜 1건" in msgs
    assert len(res.frame) == 2                                # 값이 깨진 두 행은 빠진다
    assert res.frame.loc["2025-01-07", "close"] == 104        # 중복은 마지막 값


def test_missing_ohl_falls_back_to_close_with_warning(tmp_path):
    path = _csv(tmp_path, "closeonly.csv",
                "Date,Close\n2025-01-02,100\n2025-01-03,101\n")
    raw = upload.read_table(path, "closeonly.csv")
    res = upload.build_prices(raw, upload.suggest_mapping(raw.columns), "closeonly.csv")
    assert res.ok
    assert (res.frame["high"] == res.frame["close"]).all()
    msgs = " ".join(i.message for i in res.issues)
    assert "CLV" in msgs and "Volume 컬럼이 없습니다" in msgs
    assert res.frame["volume"].isna().all()


def test_zero_volume_is_flagged(tmp_path):
    path = _csv(tmp_path, "zerovol.csv",
                "Date,Close,Volume\n2025-01-02,100,0\n2025-01-03,101,0\n2025-01-06,102,50\n")
    raw = upload.read_table(path, "zerovol.csv")
    res = upload.build_prices(raw, upload.suggest_mapping(raw.columns), "zerovol.csv")
    assert any("거래량이 0" in i.message for i in res.issues)
    assert res.stats["usable_volume"] == 1


def test_missing_required_mapping_fails_loudly(tmp_path):
    path = _csv(tmp_path, "x.csv", "A,B\n1,2\n")
    raw = upload.read_table(path, "x.csv")
    res = upload.build_prices(raw, {"date": None, "close": None}, "x.csv")
    assert not res.ok and res.failed


# ---------------- separate volume file / merge coverage ----------------

def test_merge_volume_reports_coverage(prices):
    px = prices.tail(300).copy()
    px["volume"] = np.nan
    vol = prices["volume"].tail(300).iloc[:-10]            # 마지막 10일 없음
    extra = pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp("1999-01-04")]))
    merged, stats = upload.merge_volume(px, pd.concat([vol, extra]))
    assert stats["price_rows"] == 300
    assert stats["matched"] == 290
    assert stats["price_without_volume"] == 10
    assert stats["volume_unused"] == 1                     # 가격에 없는 날짜 1건
    assert stats["coverage"] == pytest.approx(290 / 300, abs=1e-4)
    assert merged["volume"].tail(10).isna().all()          # 거래량은 ffill 하지 않는다


# ---------------- yield units ----------------

@pytest.mark.parametrize("values,expected,factor", [
    ([4.28, 4.31, 4.20], "percent", 1.0),
    ([0.0428, 0.0431, 0.0420], "decimal", 100.0),
    ([428, 431, 420], "basis_points", 0.01),
    ([42.8, 43.1, 42.0], "tenths", 0.1),
])
def test_yield_unit_autodetect(values, expected, factor):
    raw = pd.DataFrame({"Date": ["2025-01-02", "2025-01-03", "2025-01-06"], "Yield": values})
    res = upload.build_yield(raw, upload.suggest_mapping(raw.columns, upload.YIELD_FIELDS), "y.csv")
    assert res.stats["detected_unit"] == expected
    assert res.stats["factor"] == pytest.approx(factor)
    assert res.series.iloc[0] == pytest.approx(values[0] * factor)
    assert 4.0 < float(res.series.median()) < 4.5


def test_yield_unit_override_wins_and_warns():
    raw = pd.DataFrame({"Date": ["2025-01-02", "2025-01-03"], "Yield": [4.28, 4.31]})
    mapping = upload.suggest_mapping(raw.columns, upload.YIELD_FIELDS)
    res = upload.build_yield(raw, mapping, "y.csv", unit="basis_points")
    assert res.stats["applied_unit"] == "basis_points"
    assert res.series.iloc[0] == pytest.approx(0.0428)
    msgs = " ".join(i.message for i in res.issues)
    assert "자동 추정값은" in msgs                       # 사용자 선택과 추정이 다르다고 알린다
    assert any("이례적입니다" in i.message for i in res.issues)


# ---------------- loader integration + analysis-layer agnosticism ----------------

@pytest.fixture(scope="module")
def downloaded_market():
    params = Params.from_config(load_config())
    return loader.load_market(params.ticker, params.years, params.exogenous,
                              source="synthetic", use_cache=False), params


@pytest.fixture(scope="module")
def uploaded_market(downloaded_market, tmp_path_factory):
    """The *same* series, round-tripped through a CSV upload.

    Exporting what the downloader produced and re-importing it is the only way
    to prove the two paths end in identical data rather than merely similar
    data.
    """
    downloaded, params = downloaded_market
    tmp = tmp_path_factory.mktemp("upload")
    path = tmp / "ixic.csv"
    out = downloaded.prices.reset_index()
    out.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    out.to_csv(path, index=False)

    raw = upload.read_table(path, "ixic.csv")
    res = upload.build_prices(raw, upload.suggest_mapping(raw.columns), "ixic.csv")
    assert res.ok
    ov = loader.DataOverrides(prices=res.frame, price_label="ixic.csv")
    return loader.load_market(params.ticker, params.years, params.exogenous,
                              source="synthetic", overrides=ov, use_cache=False), params


def test_uploaded_market_has_the_downloaded_schema(uploaded_market, downloaded_market):
    market, params = uploaded_market
    downloaded, _ = downloaded_market
    assert list(market.prices.columns) == list(downloaded.prices.columns)
    assert market.prices.index.equals(downloaded.prices.index)
    assert market.prices.dtypes.to_dict() == downloaded.prices.dtypes.to_dict()
    pd.testing.assert_frame_equal(market.prices, downloaded.prices, rtol=1e-8)


def test_analysis_layers_are_identical_on_uploaded_data(uploaded_market, downloaded_market):
    """Features, similarity, forward returns and the audit must not care where
    the data came from."""
    market, params = uploaded_market
    downloaded, _ = downloaded_market
    fs_up, fs_dl = build_features(market, params), build_features(downloaded, params)
    pd.testing.assert_frame_equal(fs_up.values, fs_dl.values, rtol=1e-8)

    anchor = market.calendar[fs_up.valid_mask().reindex(market.calendar).fillna(False)].max()
    m_up, _ = similarity.find_similar(fs_up.values, anchor, params.similarity.weights,
                                      params.similarity, valid=fs_up.valid_mask(), max_horizon=120)
    m_dl, _ = similarity.find_similar(fs_dl.values, anchor, params.similarity.weights,
                                      params.similarity, valid=fs_dl.valid_mask(), max_horizon=120)
    assert list(m_up.index) == list(m_dl.index)

    r_up = forward.analyze(market.prices["close"], m_up, params.forward,
                           baseline_mask=fs_up.valid_mask(), index=market.calendar)
    r_dl = forward.analyze(downloaded.prices["close"], m_dl, params.forward,
                           baseline_mask=fs_dl.valid_mask(), index=downloaded.calendar)
    for h in params.forward.horizons:
        assert r_up[h].matched["n"] == r_dl[h].matched["n"]
        assert r_up[h].matched["mean"] == pytest.approx(r_dl[h].matched["mean"], rel=1e-8)

    a = audit.audit_match(market, fs_up, params, anchor, m_up.index[0], matches=m_up)
    assert a.distance["점수 100·exp(−d²/2)"] == pytest.approx(float(m_up.iloc[0]["score"]))


def test_upload_sources_are_recorded_in_meta(uploaded_market):
    market, _ = uploaded_market
    srcs = market.meta["sources"]
    assert srcs["price"]["kind"] == "upload" and srcs["price"]["name"] == "ixic.csv"
    assert srcs["volume"]["kind"] == "upload"              # 같은 파일에서 온 거래량
    assert srcs["exog:y10"]["kind"] == "auto"
    summary = quality.data_source_summary(market)
    assert list(summary["스트림"]) == ["Price (OHLC)", "Volume", "Macro · y10"]
    assert summary.loc[0, "입력 방식"] == "Manual Upload"
    assert summary.loc[0, "사용 가능 관측치"] > 4000


def test_uploaded_yield_overrides_download(prices):
    params = Params.from_config(load_config())
    raw = pd.DataFrame({"Date": prices.index.strftime("%Y-%m-%d"),
                        "Yield": np.linspace(430, 380, len(prices))})
    res = upload.build_yield(raw, upload.suggest_mapping(raw.columns, upload.YIELD_FIELDS), "t.csv")
    ov = loader.DataOverrides(exog={"y10": res.series}, exog_labels={"y10": "t.csv"})
    market = loader.load_market(params.ticker, params.years, params.exogenous,
                                source="synthetic", overrides=ov, use_cache=False)
    assert market.meta["sources"]["exog:y10"]["kind"] == "upload"
    assert 3.7 < float(market.exog["y10"].median()) < 4.4   # bp → percent 변환 반영
    checks = {c.key: c for c in quality.check_yield(market.exog["y10"], "^TNX", "10Y")}
    assert checks["yield_unit"].status == "ok"


# ---------------- proxy volume: explicit only ----------------

def test_proxy_volume_is_never_automatic(prices):
    params = Params.from_config(load_config())
    plain = loader.load_market(params.ticker, params.years, params.exogenous,
                               source="synthetic", use_cache=False)
    assert plain.meta["sources"]["volume"]["kind"] == "auto"
    assert "proxy" not in str(plain.meta["sources"]["volume"]["name"]).lower()


def test_explicit_proxy_volume_is_labelled_and_warned(prices):
    params = Params.from_config(load_config())
    proxy = synthetic_prices("QQQ", "2006-01-01")
    ov = loader.DataOverrides(prices=prices, price_label="ixic.csv",
                              volume=proxy["volume"], volume_label="QQQ proxy",
                              volume_kind="proxy")
    market = loader.load_market("^IXIC", params.years, params.exogenous,
                                source="synthetic", overrides=ov, use_cache=False)
    assert market.meta["sources"]["volume"]["kind"] == "proxy"
    checks = {c.key: c for c in quality.check_sources(market, params)}
    assert checks["volume_source"].status == "warn"
    assert checks["volume_source"].detail == "Volume Source: QQQ proxy — not Nasdaq Composite volume"
    assert "volume_merge" in checks                        # 병합 커버리지도 함께 보고
    summary = quality.data_source_summary(market)
    assert summary.loc[1, "입력 방식"] == "Proxy (사용자 지정)"


# ---------------- quality checks apply to uploaded data too ----------------

def test_quality_checks_run_on_uploaded_market(uploaded_market):
    market, params = uploaded_market
    reports = quality.run_checks(market, params)
    keys = {c.key for r in reports for c in r.checks}
    for expected in ("price_source", "volume_source", "range", "duplicates", "gaps",
                     "missing", "stale", "ohlc", "volume_usable", "dd_rate", "yield_unit"):
        assert expected in keys, expected
    frame = quality.summary_frame(reports)
    assert len(frame) > 12


def test_quality_flags_a_broken_upload(tmp_path):
    """가격이 이상한 파일은 업로드 경로로 들어와도 품질 검사에서 걸린다."""
    rows = ["Date,Open,High,Low,Close,Volume"]
    start = pd.Timestamp.today().normalize() - pd.Timedelta(days=300)
    for d in pd.bdate_range(start, periods=200):
        rows.append(f"{d.date()},100,99,101,100,0")        # high<low, volume 0
    path = _csv(tmp_path, "broken.csv", "\n".join(rows) + "\n")
    raw = upload.read_table(path, "broken.csv")
    res = upload.build_prices(raw, upload.suggest_mapping(raw.columns), "broken.csv")
    assert any("고가 < 저가" in i.message for i in res.issues)

    params = Params.from_config(load_config())
    market = loader.load_market("TEST", 1, (), source="synthetic",
                                overrides=loader.DataOverrides(prices=res.frame,
                                                               price_label="broken.csv"),
                                use_cache=False)
    checks = {c.key: c for c in quality.check_prices(market.prices)}
    assert checks["ohlc"].status == "fail"
    vchecks = {c.key: c for c in quality.check_volume(market.prices, "TEST")}
    assert vchecks["volume_usable"].status == "fail"
    assert vchecks["volume_usable"].suggestion
