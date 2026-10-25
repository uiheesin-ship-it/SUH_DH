"""Canonical major-sector names, shared across the US screeners.

The screener universe can come from Finviz OR the Nasdaq alternate source, and the
two label the major sector differently (Finviz "Financial" / "Healthcare" vs Nasdaq
"Finance" / "Health Care"). This maps every known variant to ONE canonical set —
the Finviz names, which is also what the SPDR sector-ETF map in app/base/sector.py
keys on, so normalizing here fixes both the displayed 대섹터 and the ETF resolution.

Only the MAJOR sector (대섹터) is normalized. The sub-sector / industry (중섹터) is
shown as-is from the source — there is no industry mapping (per product decision).

Unknown labels pass through unchanged, so a new source label is never dropped; it
just shows as-is (and resolves no ETF, same as before).
"""

from __future__ import annotations

# Every known major-sector label -> canonical Finviz name. Canonical values are the
# keys used by DEFAULT_SECTOR_ETF in app/base/sector.py.
SECTOR_CANON: dict[str, str] = {
    # --- Finviz names (identity / collapse the two financial variants) ---
    "Technology": "Technology",
    "Communication Services": "Communication Services",
    "Consumer Cyclical": "Consumer Cyclical",
    "Consumer Defensive": "Consumer Defensive",
    "Healthcare": "Healthcare",
    "Financial": "Financial",
    "Financial Services": "Financial",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Basic Materials": "Basic Materials",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    # --- Nasdaq names -> Finviz canonical ---
    "Finance": "Financial",
    "Health Care": "Healthcare",
    "Consumer Discretionary": "Consumer Cyclical",
    "Consumer Staples": "Consumer Defensive",
    "Telecommunications": "Communication Services",
    # Technology / Industrials / Energy / Basic Materials / Real Estate / Utilities
    # share the same spelling in both sources (covered above).
    # Nasdaq-only buckets with no clean Finviz equivalent pass through as-is:
    # "Miscellaneous", "Unknown".
}


def canonical_sector(name: str | None) -> str | None:
    """Return the canonical (Finviz-style) major-sector name for ``name``.

    None/empty pass through as None; unknown labels pass through unchanged so a new
    source label is never silently dropped."""
    if not name:
        return name
    return SECTOR_CANON.get(name, name)
