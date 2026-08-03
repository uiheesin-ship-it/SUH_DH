"""Config must not crash on a bad integer env var (spec §23 robustness).

A repo Variable mistakenly set to a non-numeric string (e.g. 'true') must fall
back to the default instead of breaking config loading for the whole app.
"""

from __future__ import annotations


def test_bad_int_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("EAI_HARVEST_DAILY_BUDGET", "true")
    monkeypatch.setenv("EAI_HARVEST_QUARTERS_PER_TICKER", "")
    from app.eai import config
    config.reset_cache()
    s = config.settings()
    assert s.harvest_daily_budget == 20          # default, not a crash
    assert s.harvest_quarters_per_ticker == 2
    config.reset_cache()


def test_good_int_env_is_honored(monkeypatch):
    monkeypatch.setenv("EAI_HARVEST_DAILY_BUDGET", "20")
    from app.eai import config
    config.reset_cache()
    assert config.settings().harvest_daily_budget == 20
    config.reset_cache()
