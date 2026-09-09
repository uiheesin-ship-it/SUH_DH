"""Deterministic synthetic bars for offline runs and tests.

``app.base.data._demo_bars`` builds an uptrend into a tightening base, which is
the right fixture for the base and flat screeners and exactly the wrong one
here — it never produces a bottom. These shapes cover the four cases this
screener has to tell apart, and double as the test fixtures:

    TURNA  decline -> trough -> tight base -> price at the right edge   (keep)
    TURNB  decline -> rounding bottom, price back near the left rim     (keep)
    KNIFE  still declining, low made a few days ago                     (reject)
    GONEC  decline -> base -> already broke out and ran 30%             (reject)
"""

from __future__ import annotations

import math

_N = 420


def _wobble(i: int, seed: int, amp: float) -> float:
    """Smooth, seed-dependent noise — no RNG, so a resumed build is identical."""
    return amp * (math.sin((i + seed) / 5.0) + 0.5 * math.sin((i + seed) / 11.0))


def _assemble(ticker: str, closes: list[float], vols: list[float]) -> dict:
    """Turn a close-price shape into OHLCV bars.

    The high-frequency jitter here is not decoration: without ~1.5% of
    day-to-day movement the synthetic series trips ``min_base_daily_vol``, the
    deal-pinned/dead-stock gate, and every fixture is silently dropped before it
    reaches the logic under test.
    """
    seed = sum(ord(ch) for ch in ticker)
    o, h, l, c, v, dates = [], [], [], [], [], []
    for i, px in enumerate(closes):
        px = max(0.5, px) * (1 + 0.014 * math.sin(i * 2.399 + seed))
        span = abs(_wobble(i, seed, 0.012)) + 0.004
        hi = px * (1 + span)
        lo = px * (1 - span)
        o.append(round((hi + lo) / 2, 4))
        h.append(round(hi, 4))
        l.append(round(lo, 4))
        c.append(round(px, 4))
        v.append(int(max(50_000, vols[i])))
        dates.append(f"D{i:04d}")
    return {"ticker": ticker, "dates": dates, "open": o, "high": h,
            "low": l, "close": c, "volume": v}


def _decline_then_base(ticker: str, *, peak: float, trough: float,
                       decline_end: int, base_end_pos: float,
                       base_amp: float, tighten: bool = True) -> dict:
    """Generic shape: flat top, decline to a trough, then a base whose last
    close sits ``base_end_pos`` of the way up its own range."""
    seed = sum(ord(ch) for ch in ticker)
    closes, vols = [], []
    base_len = _N - decline_end
    band = trough * base_amp
    for i in range(_N):
        if i < 60:
            px = peak * (1 + _wobble(i, seed, 0.01))
            vol = 3_000_000
        elif i < decline_end:
            k = (i - 60) / max(1, decline_end - 60)
            px = peak * (1 - k) + trough * k
            px *= 1 + _wobble(i, seed, 0.02)
            vol = 3_000_000 * (1 + 0.8 * k)      # heavy on the way down
        else:
            k = (i - decline_end) / max(1, base_len - 1)
            amp = band * ((1 - 0.75 * k) if tighten else 1.0)
            # Drift the base centre up toward base_end_pos across the window.
            centre = trough * (1 + 0.02) + band * base_end_pos * k
            px = centre + amp * math.sin((i + seed) / 6.0)
            vol = 3_000_000 * (0.45 - 0.15 * k)  # dries up as it builds
        closes.append(px)
        vols.append(vol)
    return _assemble(ticker, closes, vols)


def bars(ticker: str) -> dict:
    t = ticker.upper()
    if t == "TURNB":
        # Rounding bottom: the trough sits mid-window, the right side climbs
        # back toward the left rim. Exercises the cup case that a front-third
        # slope test would wrongly reject.
        seed = sum(ord(ch) for ch in t)
        closes, vols = [], []
        peak, trough = 44.0, 22.0
        for i in range(_N):
            if i < 60:
                px = peak * (1 + _wobble(i, seed, 0.01)); vol = 3_000_000
            elif i < 200:
                k = (i - 60) / 140.0
                px = peak * (1 - k) + trough * k
                px *= 1 + _wobble(i, seed, 0.02); vol = 3_500_000
            else:
                # Symmetric U from the trough back up to ~85% of the rim drop.
                k = (i - 200) / float(_N - 200 - 1)
                px = trough + (peak - trough) * 0.38 * (k ** 1.6)
                px *= 1 + _wobble(i, seed, 0.012 * (1 - 0.5 * k))
                vol = 3_000_000 * (0.5 - 0.1 * k)
            closes.append(px); vols.append(vol)
        return _assemble(t, closes, vols)

    if t == "KNIFE":
        # Never stops falling: the low is made in the last few bars, so both the
        # fresh-52w-low gate and low_early_frac must reject it.
        seed = sum(ord(ch) for ch in t)
        closes, vols = [], []
        for i in range(_N):
            k = i / float(_N - 1)
            px = 30.0 * (1 - 0.78 * k) * (1 + _wobble(i, seed, 0.02))
            closes.append(px); vols.append(4_000_000 * (1 + k))
        return _assemble(t, closes, vols)

    if t == "GONEC":
        # Built a fine base and then left: +32% above the base high, which is
        # past max_extension, so every window must come back extended.
        seed = sum(ord(ch) for ch in t)
        closes, vols = [], []
        peak, trough = 70.0, 30.0
        for i in range(_N):
            if i < 60:
                px = peak * (1 + _wobble(i, seed, 0.01)); vol = 3_000_000
            elif i < 220:
                k = (i - 60) / 160.0
                px = peak * (1 - k) + trough * k
                px *= 1 + _wobble(i, seed, 0.02); vol = 3_500_000
            elif i < 380:
                px = trough * 1.05 * (1 + _wobble(i, seed, 0.015)); vol = 1_400_000
            else:
                k = (i - 380) / 39.0
                px = trough * 1.10 * (1 + 0.55 * k); vol = 5_000_000
            closes.append(px); vols.append(vol)
        return _assemble(t, closes, vols)

    # TURNA and anything else: decline into a tightening base, price at the top.
    return _decline_then_base(t, peak=40.0, trough=17.0, decline_end=290,
                              base_end_pos=0.9, base_amp=0.07)
