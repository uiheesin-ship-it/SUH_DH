"""HTTP adapter for the Market Regime Lab.

This module contains **no analysis**. It parses a request, calls the very same
functions the Streamlit app calls (``app.regime.*``), and serialises what they
return:

    load_market → build_features → candidate_scores/decluster → forward.analyze
    quality.run_checks · audit.audit_match · validation.walk_forward · viz.*

Charts are the Plotly figures built by ``app/regime/viz.py``, handed to the
browser as figure JSON — so the dashboard draws exactly what Streamlit drew.

Uploaded files never touch disk: they are parsed in memory and the resulting
frames live in a short-TTL in-process store so follow-up calls (audit,
walk-forward) do not have to re-upload or re-download anything.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Body, File, Form, UploadFile
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/regime")

SESSION_TTL = 1800.0          # 30분 — 업로드/로딩 결과를 재사용하는 창
_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def _put(key: str, value: Any) -> str:
    now = time.time()
    with _lock:
        for k, (ts, _) in list(_store.items()):
            if now - ts > SESSION_TTL:
                _store.pop(k, None)
        _store[key] = (now, value)
    return key


def _get(key: str) -> Any:
    with _lock:
        hit = _store.get(key)
    if not hit or time.time() - hit[0] > SESSION_TTL:
        return None
    return hit[1]


def _err(message: str, detail: str = "", status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message, "detail": detail})


# ----------------------------------------------------------------- parameters

def _params(payload: dict):
    """Merge the UI's parameter overrides onto the configured defaults."""
    from app.regime import config as regime_config

    cfg = regime_config.deep_merge(regime_config.load_config(), payload.get("params") or {})
    return regime_config.Params.from_config(cfg)


def _market(payload: dict, params):
    """Load (or reuse) the dataset described by the request."""
    from app.regime.data import loader, upload

    data = payload.get("data") or {}
    session = data.get("session")
    if session:
        cached = _get(str(session))
        if cached is not None:
            return cached["market"], str(session), cached.get("notes", [])

    source = "synthetic" if data.get("offline") else "auto"
    overrides = None
    notes: list[dict] = []

    if str(data.get("mode", "auto")) == "manual":
        overrides = loader.DataOverrides()
        price = data.get("price") or {}
        if price.get("token"):
            raw = _get(str(price["token"]))
            if raw is None:
                return None, "", [{"level": "fail", "message": "업로드 세션이 만료됐습니다. 파일을 다시 올려 주세요."}]
            res = upload.build_prices(raw["frame"], price.get("mapping") or {}, raw["name"])
            notes += [{"level": i.level, "message": f"[가격 {raw['name']}] {i.message}"} for i in res.issues]
            if not res.ok:
                return None, "", notes
            overrides.prices, overrides.price_label = res.frame, raw["name"]

        volume = data.get("volume") or {}
        if volume.get("token"):
            raw = _get(str(volume["token"]))
            if raw is not None:
                res = upload.build_volume(raw["frame"], volume.get("mapping") or {}, raw["name"])
                notes += [{"level": i.level, "message": f"[거래량 {raw['name']}] {i.message}"} for i in res.issues]
                if res.ok:
                    overrides.volume = res.series
                    overrides.volume_label, overrides.volume_kind = raw["name"], "upload"

        macro = data.get("yield") or {}
        if macro.get("token"):
            raw = _get(str(macro["token"]))
            if raw is not None:
                res = upload.build_yield(raw["frame"], macro.get("mapping") or {}, raw["name"],
                                         unit=str(macro.get("unit", "auto")))
                notes += [{"level": i.level, "message": f"[10Y {raw['name']}] {i.message}"} for i in res.issues]
                if res.ok:
                    key = str(params.exogenous[0].get("key")) if params.exogenous else "y10"
                    overrides.exog[key] = res.series
                    overrides.exog_labels[key] = raw["name"]

    market = loader.load_market(params.ticker, params.years, params.exogenous,
                                source=source, overrides=overrides)
    token = str(uuid.uuid4())
    if not market.empty:
        _put(token, {"market": market, "notes": notes})
    return market, token, notes


def _features(session: str, market, params):
    """Feature frame, cached per (session, feature parameters)."""
    from app.regime.features import build_features

    sig = json.dumps({"f": params.features.__dict__, "d": params.distribution.__dict__},
                     default=str, sort_keys=True)
    key = f"features:{session}:{sig}"
    cached = _get(key)
    if cached is not None:
        return cached
    fs = build_features(market, params)
    _put(key, fs)
    return fs


# ------------------------------------------------------------- serialisation

def _clean(value):
    import math

    if value is None:
        return None
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, (bool, int, str)):
        return value
    try:
        import numpy as np

        if isinstance(value, (np.floating, np.integer, np.bool_)):
            return _clean(value.item())
    except Exception:
        pass
    return str(value)


def _frame(df, index_label: str | None = None) -> dict:
    """DataFrame → {columns, rows} (NaN 은 null)."""
    import pandas as pd

    if df is None or len(df) == 0:
        return {"columns": [], "rows": []}
    out = df.copy()
    if index_label:
        idx = out.index
        labels = [str(v.date()) if isinstance(v, pd.Timestamp) else str(v) for v in idx]
        out.insert(0, index_label, labels)
    columns = [str(c) for c in out.columns]
    rows = [[_clean(v) for v in row] for row in out.itertuples(index=False, name=None)]
    return {"columns": columns, "rows": rows}


def _figure(fig) -> dict:
    return json.loads(fig.to_json())


def _quality_payload(reports) -> dict:
    from app.regime import quality

    return {
        "status": quality.overall_status(reports),
        "table": _frame(quality.summary_frame(reports)),
        "problems": [{"series": r.series, "label": c.label, "status": c.status,
                      "value": c.value, "detail": c.detail, "suggestion": c.suggestion}
                     for r in reports for c in r.problems()],
        "notes": [{"series": r.series, "label": c.label, "detail": c.detail,
                   "suggestion": c.suggestion}
                  for r in reports for c in r.notes()],
    }


def _state_payload(market, fs, params, anchor) -> dict:
    groups: dict[str, list] = {}
    row = fs.values.loc[anchor]
    for key in fs.values.columns:
        spec = fs.specs.get(key)
        if spec is None:
            continue
        groups.setdefault(spec.group, []).append({
            "key": key, "label": spec.label, "value": _clean(row.get(key)),
            "formatted": spec.format(row.get(key)), "description": spec.description,
        })
    px = market.prices.loc[anchor]
    flags = fs.aux.loc[:anchor]
    recent = flags[flags["dd_flag"].fillna(False)].tail(10) if "dd_flag" in flags.columns else None
    dd_table = _frame(recent[["ret_pct", "vol_ratio", "clv"]].sort_index(ascending=False),
                      index_label="날짜") if recent is not None and len(recent) else {"columns": [], "rows": []}
    dp = params.distribution
    return {
        "date": str(anchor.date()),
        "close": _clean(px["close"]),
        "groups": [{"group": g, "items": items} for g, items in groups.items()],
        "distribution": {
            "condition": (f"일간 수익률 ≤ -{dp.drop_pct}% · 거래량 ≥ 전일 × "
                          f"{1 + dp.volume_bump_pct / 100:.2f} · CLV ≤ {dp.clv_max} · "
                          f"최근 {dp.lookback} 거래일"),
            "recent": dd_table,
        },
    }


def _forward_payload(results, params) -> dict:
    horizons = sorted(results)
    def stats(s, r):
        return {
            "n": s["n"], "mean": _clean(s["mean"]), "median": _clean(s["median"]),
            "win_rate": _clean(s["win_rate"]), "p25": _clean(s["p25"]), "p75": _clean(s["p75"]),
            "min": _clean(s["min"]), "max": _clean(s["max"]), "std": _clean(s["std"]),
            "mdd_mean": _clean(s["mdd_mean"]),
            "ci_mean": [_clean(x) for x in s["ci_mean"]],
            "ci_median": [_clean(x) for x in s["ci_median"]],
        }
    return {
        "ci_level": params.forward.ci_level,
        "independence": params.forward.independence,
        "ci_method": params.forward.ci_method,
        "horizons": horizons,
        "rows": [{
            "horizon": h,
            "matched": stats(results[h].matched, results[h]),
            "baseline": stats(results[h].baseline, results[h]),
            "diff_mean": _clean(results[h].diff_mean),
            "diff_median": _clean(results[h].diff_median),
            "diff_win_rate": _clean(results[h].diff_win_rate),
            "baseline_pctile": _clean(results[h].baseline_pctile),
            "ci_excludes_zero": bool(results[h].ci_excludes_zero),
            "n_episodes": results[h].matched.get("n_episodes", 0),
            "ess": _clean(results[h].ess),
            "ci_width": _clean(results[h].ci_width),
            "ci_width_iid": _clean(results[h].ci_width_iid),
            "dropped": results[h].dropped,
            "warnings": results[h].warnings,
        } for h in horizons],
    }


# ------------------------------------------------------------------ endpoints

@router.get("/defaults")
def defaults():
    """Parameter defaults + feature descriptors so the UI can build its controls.

    The feature list is taken from the real builders (a tiny synthetic market is
    enough to enumerate them), so labels, groups and default weights can never
    drift from the analysis.
    """
    try:
        from app.regime.config import Params, load_config
        from app.regime.data import loader
        from app.regime.features import build_features

        cached = _get("defaults")
        if cached is not None:
            return cached

        cfg = load_config()
        params = Params.from_config(cfg)
        sample = loader.load_market(params.ticker, 3, params.exogenous,
                                    source="synthetic", use_cache=False)
        fs = build_features(sample, params)
        specs = [{"key": key, "label": fs.specs[key].label, "group": fs.specs[key].group,
                  "fmt": fs.specs[key].fmt, "default_weight": fs.specs[key].default_weight,
                  "description": fs.specs[key].description}
                 for key in fs.values.columns if key in fs.specs]
        payload = {"config": cfg, "features": specs}
        _put("defaults", payload)
        return payload
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("regime defaults failed")
        return _err("기본 설정을 불러오지 못했습니다.", str(exc), 500)


@router.post("/inspect")
async def inspect(file: UploadFile = File(...), kind: str = Form("price")):
    """Read an uploaded CSV/XLSX and propose a column mapping (no analysis yet)."""
    try:
        from app.regime.data import upload

        content = await file.read()
        raw = upload.read_table(content, file.filename)
        fields = {"price": upload.PRICE_FIELDS, "volume": ("date", "volume"),
                  "yield": upload.YIELD_FIELDS}.get(kind, upload.PRICE_FIELDS)
        mapping = upload.suggest_mapping(raw.columns, fields)
        token = _put(str(uuid.uuid4()), {"frame": raw, "name": file.filename, "kind": kind})
        preview = raw.head(3).astype(str)
        return {
            "token": token, "name": file.filename, "rows": int(len(raw)),
            "columns": [str(c) for c in raw.columns],
            "fields": list(fields), "mapping": mapping,
            "preview": _frame(preview),
        }
    except Exception as exc:
        log.exception("regime inspect failed")
        return _err("파일을 읽지 못했습니다.", str(exc))


@router.post("/analyze")
def analyze(payload: dict = Body(default={})):
    """Full run: data → features → matches → forward returns → charts."""
    try:
        import pandas as pd

        from app.regime import matching, quality, similarity, viz
        from app.regime.forward import analyze as forward_analyze
        from app.regime.forward import forward_returns
        from app.regime.matching import Condition

        params = _params(payload)
        market, session, notes = _market(payload, params)
        if market is None or market.empty:
            return _err("데이터를 불러오지 못했습니다.",
                        "; ".join(n["message"] for n in notes) or
                        "자동 내려받기가 막혀 있다면 CSV/XLSX 를 직접 올리거나 오프라인 데모를 쓰세요.")

        fs = _features(session, market, params)
        valid = fs.valid_mask()
        usable = market.calendar[valid.reindex(market.calendar).fillna(False)]
        if len(usable) == 0:
            return _err("feature 를 계산할 수 있는 날짜가 없습니다.",
                        "기간을 늘리거나 window 를 줄여 보세요 (SMA200·52주 고점에는 최소 250거래일 필요).")

        anchor_req = (payload.get("anchor") or "").strip()
        anchor = usable.max()
        if anchor_req:
            prior = usable[usable <= pd.Timestamp(anchor_req)]
            anchor = prior.max() if len(prior) else anchor

        mode = str(payload.get("mode", "similarity"))
        max_h = int(max(params.forward.horizons))
        if mode == "strict":
            conds = [Condition(key=str(c["key"]), op=str(c["op"]), value=float(c["value"]),
                               value2=None if c.get("value2") in (None, "") else float(c["value2"]))
                     for c in (payload.get("conditions") or [])]
            scored, info = matching.strict_candidates(fs.values, conds, anchor, params.similarity,
                                                      weights=params.similarity.weights,
                                                      max_horizon=max_h, valid=valid)
            matches = similarity.decluster(scored.fillna({"score": 0.0}), market.calendar,
                                           params.similarity.min_gap,
                                           pick=params.similarity.episode_pick if params.similarity.weights else "first",
                                           top_n=None)
            matches = matches.sort_values("score", ascending=False).head(params.similarity.top_n)
        else:
            scored, info = similarity.candidate_scores(fs.values, anchor, params.similarity.weights,
                                                       params.similarity, valid=valid, max_horizon=max_h)
            matches = similarity.decluster(scored, market.calendar, params.similarity.min_gap,
                                           pick=params.similarity.episode_pick,
                                           top_n=params.similarity.top_n)

        table = viz.build_match_table(matches, fs, market.prices["close"], params.forward.horizons,
                                      keys=info.used_keys or list(fs.values.columns)[:6])
        results = forward_analyze(market.prices["close"], matches, params.forward,
                                  baseline_mask=valid, min_gap=params.similarity.min_gap,
                                  index=market.calendar, episode_pick=params.similarity.episode_pick)
        reports = quality.run_checks(market, params)

        exog_label = params.exogenous[0]["label"] if params.exogenous else "Macro"
        charts = {
            "price": _figure(viz.price_chart(
                market, fs, table, params.forward.horizons,
                shade_horizon=int(payload.get("shade") or params.forward.horizons[0]),
                log_scale=bool(payload.get("log_scale", True)),
                show_sma=tuple(int(w) for w in (payload.get("show_sma") or [50, 200])),
                anchor=anchor, exog_label=exog_label)),
            "forward_bar": _figure(viz.forward_bar_chart(results, params.forward.ci_level)),
        }
        hist_h = int(payload.get("hist_horizon") or (params.forward.horizons[1]
                                                     if len(params.forward.horizons) > 1
                                                     else params.forward.horizons[0]))
        fwd = forward_returns(market.prices["close"], params.forward.horizons)[f"fwd_{hist_h}"]
        charts["distribution"] = _figure(viz.distribution_chart(
            fwd.reindex(matches.index), fwd[valid], hist_h))

        display = table.copy()
        rename = {"score": "유사도", "distance": "거리", "close": "종가"}
        for key in list(display.columns):
            if key in fs.specs:
                rename[key] = fs.specs[key].label
        for h in params.forward.horizons:
            rename[f"fwd_{int(h)}"] = f"+{int(h)}일 (%)"
        rename[f"mdd_{max_h}"] = f"+{max_h}일 최대낙폭 (%)"

        return {
            "session": session,
            "ticker": market.ticker,
            "anchor": str(anchor.date()),
            "anchor_range": [str(usable.min().date()), str(usable.max().date())],
            "notes": notes,
            "series": market.meta.get("series", {}),
            "sources": _frame(quality.data_source_summary(market)),
            "quality": _quality_payload(reports),
            "state": _state_payload(market, fs, params, anchor),
            "matches": _frame(display.rename(columns=rename).round(4), index_label="날짜"),
            "match_dates": [str(pd.Timestamp(d).date()) for d in matches.index],
            "forward": _forward_payload(results, params),
            "charts": charts,
            "hist_horizon": hist_h,
            "used_features": info.used_keys,
            "dropped_features": {k: v for k, v in (info.dropped_keys or {}).items()},
            "candidates": int(len(scored)),
        }
    except Exception as exc:
        log.exception("regime analyze failed")
        return _err("분석에 실패했습니다.", str(exc), 500)


@router.post("/audit")
def audit(payload: dict = Body(default={})):
    """One match date, every intermediate value (계산 감사)."""
    try:
        import pandas as pd

        from app.regime import audit as audit_mod
        from app.regime import matching, similarity

        params = _params(payload)
        market, session, notes = _market(payload, params)
        if market is None or market.empty:
            return _err("데이터를 불러오지 못했습니다.", "세션이 만료됐다면 분석을 다시 실행하세요.")
        fs = _features(session, market, params)
        valid = fs.valid_mask()
        usable = market.calendar[valid.reindex(market.calendar).fillna(False)]
        anchor = pd.Timestamp(payload.get("anchor") or usable.max())
        date = pd.Timestamp(payload["date"])

        max_h = int(max(params.forward.horizons))
        if str(payload.get("mode", "similarity")) == "strict":
            conds = [matching.Condition(key=str(c["key"]), op=str(c["op"]), value=float(c["value"]),
                                        value2=None if c.get("value2") in (None, "") else float(c["value2"]))
                     for c in (payload.get("conditions") or [])]
            scored, _ = matching.strict_candidates(fs.values, conds, anchor, params.similarity,
                                                   weights=params.similarity.weights,
                                                   max_horizon=max_h, valid=valid)
            matches = similarity.decluster(scored.fillna({"score": 0.0}), market.calendar,
                                           params.similarity.min_gap,
                                           pick=params.similarity.episode_pick, top_n=None)
            matches = matches.sort_values("score", ascending=False).head(params.similarity.top_n)
        else:
            scored, _ = similarity.candidate_scores(fs.values, anchor, params.similarity.weights,
                                                    params.similarity, valid=valid, max_horizon=max_h)
            matches = similarity.decluster(scored, market.calendar, params.similarity.min_gap,
                                           pick=params.similarity.episode_pick,
                                           top_n=params.similarity.top_n)

        res = audit_mod.audit_match(market, fs, params, anchor, date,
                                    weights=params.similarity.weights,
                                    scored=scored, matches=matches,
                                    horizons=params.forward.horizons)
        summary = {k: _clean(v) for k, v in res.distance.items() if k != "제외된 feature"}
        return {
            "session": session,
            "date": str(res.date.date()), "anchor": str(res.anchor.date()),
            "ohlcv": _frame(res.ohlcv.round(4), index_label="날짜"),
            "trend": _frame(res.trend.round(6)),
            "distribution": _frame(res.distribution.round(6)),
            "dd_days": _frame(res.dd_days.round(4), index_label="날짜"),
            "features": _frame(res.features.round(6)),
            "summary": summary,
            "declustering": {k: str(v) for k, v in res.declustering.items()},
            "forward": _frame(res.forward.round(4)),
            "notes": res.notes,
        }
    except Exception as exc:
        log.exception("regime audit failed")
        return _err("계산 감사에 실패했습니다.", str(exc), 500)


@router.post("/validation")
def validation(payload: dict = Body(default={})):
    """Walk-forward / out-of-sample check (heavy: 수십 초)."""
    try:
        from app.regime import validation as validation_mod
        from app.regime import viz

        params = _params(payload)
        market, session, notes = _market(payload, params)
        if market is None or market.empty:
            return _err("데이터를 불러오지 못했습니다.", "세션이 만료됐다면 분석을 다시 실행하세요.")
        fs = _features(session, market, params)
        if not params.similarity.weights:
            return _err("가중치가 모두 0 입니다.", "feature 가중치를 설정한 뒤 다시 실행하세요.")

        results = validation_mod.walk_forward(fs.values, market.prices["close"],
                                              params.similarity.weights, params.similarity,
                                              params, valid=fs.valid_mask())
        summary = validation_mod.summary_table(results)
        is_rows = summary[summary["구분"] == "In-Sample"]["초과(%p)"]
        oos_rows = summary[summary["구분"] == "Out-of-Sample"]["초과(%p)"]
        return {
            "session": session,
            "table": _frame(summary.round(4)),
            "chart": _figure(viz.validation_chart(summary)),
            "in_sample": _clean(float(is_rows.mean())) if len(is_rows) else None,
            "out_of_sample": _clean(float(oos_rows.mean())) if len(oos_rows) else None,
            "horizon": params.validation.horizon,
            "mode": params.validation.mode,
        }
    except Exception as exc:
        log.exception("regime validation failed")
        return _err("검증에 실패했습니다.", str(exc), 500)


@router.post("/features.csv")
def features_csv(payload: dict = Body(default={})):
    """전체 feature 표 (다운로드용)."""
    try:
        params = _params(payload)
        market, session, _ = _market(payload, params)
        if market is None or market.empty:
            return _err("데이터를 불러오지 못했습니다.")
        fs = _features(session, market, params)
        return {"session": session, "csv": fs.values.to_csv()}
    except Exception as exc:
        log.exception("regime features csv failed")
        return _err("feature 내보내기에 실패했습니다.", str(exc), 500)
