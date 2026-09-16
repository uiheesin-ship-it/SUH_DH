"""Sidebar upload path, driven through Streamlit's AppTest.

``st.file_uploader`` cannot be set from AppTest, so the test runs the real page
with the uploader stubbed to hand back files from disk — everything else (the
mapping widgets, the parse, the loader overrides, every tab) is the production
code path. It proves the upload actually reaches the analysis, not just that
the parser works in isolation.

Run with:  python -m pytest tests/test_regime_upload_ui.py -q
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.regime.data.sources import synthetic_prices

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = '''
import io, os, sys
from pathlib import Path
sys.path.insert(0, {root!r})
import streamlit as st

FILES = {{"price_file": os.environ.get("TEST_PRICE_FILE"),
          "volume_file": os.environ.get("TEST_VOLUME_FILE"),
          "yield_file": os.environ.get("TEST_YIELD_FILE")}}

def _fake_uploader(label, **kwargs):
    path = FILES.get(kwargs.get("key"))
    if not path:
        return None
    buf = io.BytesIO(Path(path).read_bytes())
    buf.name = Path(path).name
    return buf

st.file_uploader = _fake_uploader

import app.regime.streamlit_app as regime_app
regime_app.main()
'''


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("upload_ui")
    px = synthetic_prices("^IXIC", "2006-01-01")
    out = px.reset_index()
    out.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    price_path = tmp / "my_ixic_20y.csv"
    out.to_csv(price_path, index=False)

    yield_path = tmp / "my_us10y.csv"
    pd.DataFrame({"observation_date": px.index.strftime("%Y-%m-%d"),
                  "DGS10": np.linspace(0.043, 0.038, len(px))}).to_csv(yield_path, index=False)

    script = tmp / "upload_app.py"
    script.write_text(SCRIPT.format(root=str(ROOT)), encoding="utf-8")
    return {"dir": tmp, "price": price_path, "yield": yield_path, "script": script}


def _run(files, **env):
    from streamlit.testing.v1 import AppTest

    for k in ("TEST_PRICE_FILE", "TEST_VOLUME_FILE", "TEST_YIELD_FILE"):
        os.environ.pop(k, None)
    os.environ.update(env)
    at = AppTest.from_file(str(files["script"]), default_timeout=900)
    at.run()
    # 데이터 입력 방식은 사이드바가 아니라 페이지 상단(① 데이터)에 있다.
    radio = [r for r in at.radio if r.label == "데이터 입력 방식"][0]
    radio.set_value("Manual Upload").run()
    return at


def _start_analysis(at):
    """Manual Upload 는 품질 확인 후 '분석 실행'을 눌러야 계산이 시작된다."""
    run = [b for b in at.button if b.label == "분석 실행"]
    if run:
        run[0].click().run()
    return at


def test_uploaded_csv_drives_the_whole_page(files):
    at = _run(files, TEST_PRICE_FILE=str(files["price"]), TEST_YIELD_FILE=str(files["yield"]))
    assert not at.exception, at.exception

    # 업로드 직후에는 데이터 확인 단계에서 멈춰 있어야 한다 (분석은 아직 실행 전).
    assert [h.value for h in at.subheader][:2] == ["① 데이터", "② 데이터 확인"]
    assert [b.label for b in at.button if b.label == "분석 실행"], "분석 실행 버튼이 없습니다"
    assert not at.tabs, "품질 확인 전에 분석 결과가 먼저 보이면 안 됩니다"

    _start_analysis(at)
    assert not at.exception, at.exception
    assert at.tabs and len(at.tabs) == 7

    source_lines = [m.value for m in at.markdown if m.value.startswith("데이터 소스")]
    assert source_lines, "데이터 소스 표기가 없습니다"
    assert "Manual Upload" in source_lines[0]
    assert "my_ixic_20y.csv" in source_lines[0]
    assert "my_us10y.csv" in source_lines[0]

    # 업로드 데이터로도 분석이 끝까지 돈다: 상태·매칭·forward 탭의 지표가 채워진다
    labels = {m.label: m.value for m in at.metric}
    assert any(lbl.startswith("^IXIC 최종 업데이트") for lbl in labels)
    assert "거리 d" in labels and "유사도 score" in labels      # 계산 감사 탭
    assert not [e for e in at.error]

    summary = [df for df in at.dataframe
               if "스트림" in getattr(df.value, "columns", [])]
    assert summary, "Data Source Summary 표가 없습니다"
    frame = summary[0].value
    assert frame.loc[0, "입력 방식"] == "Manual Upload"
    assert frame.loc[0, "파일명 / 제공자"] == "my_ixic_20y.csv"
    assert frame.loc[1, "사용 가능 관측치"] > 4000


def test_yield_unit_override_is_applied(files):
    """decimal(0.04…) 파일을 percent 로 잘못 지정하면 경고가 뜬다."""
    at = _run(files, TEST_PRICE_FILE=str(files["price"]), TEST_YIELD_FILE=str(files["yield"]))
    unit = [s for s in at.selectbox if s.label == "단위"][0]
    unit.set_value("percent (4.28)").run()
    assert not at.exception
    warnings = " ".join(w.value for w in at.warning)
    assert "이례적입니다" in warnings or "10Y" in warnings


def test_proxy_volume_requires_explicit_consent(files):
    at = _run(files, TEST_PRICE_FILE=str(files["price"]))
    vol_mode = [r for r in at.radio if r.label == "거래량 소스"][0]
    vol_mode.set_value("다른 종목의 거래량(proxy)").run()
    assert not at.exception
    # 동의 체크박스를 누르기 전에는 proxy 가 적용되지 않는다
    source_lines = [m.value for m in at.markdown if m.value.startswith("데이터 소스")]
    assert "proxy" not in source_lines[0].lower()
    assert any("Volume Source:" in w.value for w in at.warning)
